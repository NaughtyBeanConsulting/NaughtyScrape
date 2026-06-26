"""Tests for the workspace-scoped CRM: timeline, ownership, tags, tasks, queues,
plus multi-workspace isolation, lazy state, membership access, and switching."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    Activity,
    ActivityType,
    Business,
    Contact,
    LeadAssignment,
    LeadStatus,
    Tag,
    Task,
    Workspace,
    WorkspaceLead,
    WorkspaceMembership,
)
from .services import crm

User = get_user_model()


def make_business(**kw):
    kw.setdefault("place_id", f"place-{Business.objects.count() + 1}")
    kw.setdefault("name", "Test Cafe")
    return Business.objects.create(**kw)


def make_workspace(name="Default", members=(), **kw):
    ws = Workspace.objects.create(name=name, **kw)
    for user in members:
        WorkspaceMembership.objects.create(workspace=ws, user=user)
    return ws


class CrmServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rep@example.com", "pw12345678")
        self.ws = make_workspace(members=[self.user])
        self.biz = make_business(international_phone="+27 11 555 0000")
        self.wl = crm.get_or_create_lead(self.ws, self.biz)

    def test_log_activity_sets_last_activity_and_contacted(self):
        self.assertIsNone(self.wl.last_activity_at)
        act = crm.log_activity(self.wl, user=self.user, kind=ActivityType.CALL, body="Rang owner")
        self.wl.refresh_from_db()
        self.assertEqual(act.kind, ActivityType.CALL)
        self.assertIsNotNone(self.wl.last_activity_at)
        # An outreach touch backfills contacted_at the first time.
        self.assertIsNotNone(self.wl.contacted_at)

    def test_note_does_not_set_contacted(self):
        crm.log_activity(self.wl, user=self.user, kind=ActivityType.NOTE, body="just a note")
        self.wl.refresh_from_db()
        self.assertIsNone(self.wl.contacted_at)
        self.assertIsNotNone(self.wl.last_activity_at)

    def test_change_status_logs_and_is_idempotent(self):
        self.assertTrue(crm.change_status(self.wl, LeadStatus.CONTACTED, user=self.user))
        self.wl.refresh_from_db()
        self.assertEqual(self.wl.status, LeadStatus.CONTACTED)
        self.assertIsNotNone(self.wl.contacted_at)
        self.assertEqual(
            Activity.objects.filter(business=self.biz, workspace=self.ws,
                                    kind=ActivityType.STATUS).count(), 1)
        # No-op when status is unchanged.
        self.assertFalse(crm.change_status(self.wl, LeadStatus.CONTACTED, user=self.user))
        self.assertEqual(
            Activity.objects.filter(business=self.biz, workspace=self.ws,
                                    kind=ActivityType.STATUS).count(), 1)

    def test_assign_lead_records_owner_history_and_activity(self):
        self.assertTrue(crm.assign_lead(self.wl, self.user, by=self.user))
        self.wl.refresh_from_db()
        self.assertEqual(self.wl.assigned_to, self.user)
        self.assertEqual(
            LeadAssignment.objects.filter(business=self.biz, workspace=self.ws).count(), 1)
        self.assertEqual(
            Activity.objects.filter(business=self.biz, workspace=self.ws,
                                    kind=ActivityType.ASSIGNMENT).count(), 1)
        # Re-assigning to same user is a no-op.
        self.assertFalse(crm.assign_lead(self.wl, self.user, by=self.user))

    def test_tag_add_remove(self):
        tag = Tag.objects.create(name="Hot Lead", workspace=self.ws)
        self.assertTrue(crm.add_tag(self.wl, tag, user=self.user))
        self.assertFalse(crm.add_tag(self.wl, tag, user=self.user))
        self.assertIn(tag, self.wl.tags.all())
        self.assertTrue(crm.remove_tag(self.wl, tag, user=self.user))
        self.assertNotIn(tag, self.wl.tags.all())

    def test_task_create_and_complete(self):
        task = crm.create_task(self.wl, title="Follow up", assignee=self.user, by=self.user)
        self.assertFalse(task.is_done)
        self.assertEqual(task.workspace, self.ws)
        self.assertEqual(
            Activity.objects.filter(business=self.biz, workspace=self.ws,
                                    kind=ActivityType.TASK).count(), 1)
        crm.complete_task(task, user=self.user)
        task.refresh_from_db()
        self.assertTrue(task.is_done)
        self.assertIsNotNone(task.completed_at)
        self.assertEqual(
            Activity.objects.filter(business=self.biz, workspace=self.ws,
                                    kind=ActivityType.TASK).count(), 2)


class TaskQueryTests(TestCase):
    def test_overdue_and_due_today_flags(self):
        ws = make_workspace()
        biz = make_business()
        today = timezone.localdate()
        overdue = Task.objects.create(
            workspace=ws, business=biz, title="late", due_date=today - timedelta(days=1))
        due = Task.objects.create(
            workspace=ws, business=biz, title="now", due_date=today)
        self.assertTrue(overdue.is_overdue)
        self.assertFalse(overdue.is_due_today)
        self.assertTrue(due.is_due_today)
        self.assertFalse(due.is_overdue)


class TagSlugTests(TestCase):
    def test_slug_autogenerated_and_unique_within_workspace(self):
        ws = make_workspace()
        a = Tag.objects.create(name="VIP Roaster", workspace=ws)
        self.assertEqual(a.slug, "vip-roaster")
        b = Tag.objects.create(name="VIP Roaster!", workspace=ws)  # clashing slug base
        self.assertNotEqual(a.slug, b.slug)

    def test_same_name_allowed_in_different_workspaces(self):
        ws1, ws2 = make_workspace(name="One"), make_workspace(name="Two")
        t1 = Tag.objects.create(name="Hot", workspace=ws1)
        t2 = Tag.objects.create(name="Hot", workspace=ws2)
        self.assertEqual(t1.slug, t2.slug)  # same slug, different workspace — fine


class ViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            "admin@example.com", "pw12345678", role="admin", is_staff=True, is_superuser=True
        )
        self.rep = User.objects.create_user("rep@example.com", "pw12345678")
        self.ws = make_workspace(is_default=True, members=[self.rep, self.admin])
        self.biz = make_business(name="Bean Bar", international_phone="+27 11 555 1234")
        self.wl = crm.get_or_create_lead(self.ws, self.biz)
        self.client.force_login(self.rep)

    def _wl(self):
        return WorkspaceLead.objects.get(workspace=self.ws, business=self.biz)

    def test_lead_detail_and_leads_pages_render(self):
        crm.assign_lead(self.wl, self.rep, by=self.rep)
        crm.log_activity(self.wl, user=self.rep, kind=ActivityType.NOTE, body="hello")
        Contact.objects.create(business=self.biz, name="Jane")
        resp = self.client.get(reverse("scraper:lead_detail", args=[self.biz.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Timeline")
        self.assertContains(resp, "Jane")
        resp = self.client.get(reverse("scraper:leads"))
        self.assertEqual(resp.status_code, 200)

    def test_work_page_renders(self):
        crm.create_task(self.wl, title="Call back", assignee=self.rep, by=self.rep,
                        due_date=timezone.localdate())
        resp = self.client.get(reverse("scraper:work"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Call back")

    def test_lead_add_activity_creates_timeline_entry(self):
        url = reverse("scraper:lead_activity", args=[self.biz.pk])
        resp = self.client.post(url, {"kind": "call", "body": "Spoke to manager"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            Activity.objects.filter(business=self.biz, workspace=self.ws, kind="call").count(), 1)

    def test_lead_add_activity_rejects_empty_body(self):
        url = reverse("scraper:lead_activity", args=[self.biz.pk])
        self.client.post(url, {"kind": "note", "body": "   "})
        self.assertEqual(Activity.objects.filter(business=self.biz, workspace=self.ws).count(), 0)

    def test_assign_to_me(self):
        url = reverse("scraper:lead_assign", args=[self.biz.pk])
        self.client.post(url, {"assignee": "me"})
        self.assertEqual(self._wl().assigned_to, self.rep)

    def test_add_contact(self):
        url = reverse("scraper:lead_add_contact", args=[self.biz.pk])
        self.client.post(url, {"name": "Jane Owner", "email": "jane@bean.bar", "is_primary": "on"})
        self.assertEqual(self.biz.contacts.count(), 1)
        self.assertTrue(self.biz.contacts.first().is_primary)

    def test_add_task_via_view(self):
        url = reverse("scraper:lead_add_task", args=[self.biz.pk])
        self.client.post(url, {"title": "Email pricing", "due_date": ""})
        self.assertEqual(Task.objects.filter(business=self.biz, workspace=self.ws).count(), 1)

    def test_bulk_assign_and_status(self):
        b2 = make_business(name="Second", national_phone="555")
        self.client.post(reverse("scraper:leads_bulk"), {
            "action": "assign", "assignee": "me", "ids": [self.biz.pk, b2.pk],
        })
        self.assertEqual(
            WorkspaceLead.objects.filter(workspace=self.ws, assigned_to=self.rep).count(), 2)
        self.client.post(reverse("scraper:leads_bulk"), {
            "action": "status", "status": LeadStatus.CONTACTED, "ids": [self.biz.pk, b2.pk],
        })
        self.assertEqual(
            WorkspaceLead.objects.filter(workspace=self.ws, status=LeadStatus.CONTACTED).count(), 2)

    def test_bulk_tag_and_task(self):
        tag = Tag.objects.create(name="Conference", workspace=self.ws)
        self.client.post(reverse("scraper:leads_bulk"), {
            "action": "tag", "tag": tag.pk, "ids": [self.biz.pk],
        })
        self.assertIn(tag, self._wl().tags.all())
        self.client.post(reverse("scraper:leads_bulk"), {
            "action": "task", "task_title": "Bulk follow-up", "assignee": "me",
            "due_date": "2026-07-01", "ids": [self.biz.pk],
        })
        self.assertEqual(
            Task.objects.filter(business=self.biz, workspace=self.ws,
                                title="Bulk follow-up").count(), 1)

    def test_leads_filter_mine_and_ready(self):
        crm.assign_lead(self.wl, self.rep, by=self.rep)
        resp = self.client.get(reverse("scraper:leads_table"), {"view": "mine"})
        self.assertContains(resp, "Bean Bar")
        # "ready" needs NEW status + contactable; biz has a phone and is NEW.
        resp = self.client.get(reverse("scraper:leads_table"), {"view": "ready"})
        self.assertContains(resp, "Bean Bar")

    def test_tasks_page_scope_state(self):
        crm.create_task(self.wl, title="Mine open", assignee=self.rep, by=self.rep)
        resp = self.client.get(reverse("scraper:tasks"), {"scope": "mine", "state": "open"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Mine open")

    def test_any_member_can_create_workspace_tag(self):
        # Tags are per-workspace; a plain member (not just an admin) can create one.
        self.client.post(reverse("scraper:tag_create"), {"name": "Yes", "color": "sky"})
        self.assertTrue(Tag.objects.filter(name="Yes", workspace=self.ws).exists())

    def test_status_change_via_inline_endpoint_logs_activity(self):
        url = reverse("scraper:lead_status", args=[self.biz.pk])
        self.client.post(url, {f"status-{self.biz.pk}": LeadStatus.QUALIFIED})
        self.assertEqual(self._wl().status, LeadStatus.QUALIFIED)
        self.assertTrue(
            Activity.objects.filter(business=self.biz, workspace=self.ws,
                                    kind=ActivityType.STATUS).exists())


class WorkspaceIsolationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rep@example.com", "pw12345678")
        self.ws_a = make_workspace(name="Alpha", members=[self.user])
        self.ws_b = make_workspace(name="Beta", members=[self.user])
        self.biz = make_business(name="Shared Cafe", international_phone="+27 11 555 9999")

    def test_status_is_independent_per_workspace(self):
        wl_a = crm.get_or_create_lead(self.ws_a, self.biz)
        crm.change_status(wl_a, LeadStatus.CONTACTED, user=self.user)
        in_a = Business.objects.with_workspace_state(self.ws_a).get(pk=self.biz.pk)
        in_b = Business.objects.with_workspace_state(self.ws_b).get(pk=self.biz.pk)
        self.assertEqual(in_a.effective_status, LeadStatus.CONTACTED)
        # B never touched the lead — it reads as New with no WorkspaceLead row.
        self.assertEqual(in_b.effective_status, LeadStatus.NEW)
        self.assertEqual(WorkspaceLead.objects.filter(business=self.biz).count(), 1)

    def test_owner_and_timeline_isolated(self):
        wl_a = crm.get_or_create_lead(self.ws_a, self.biz)
        crm.assign_lead(wl_a, self.user, by=self.user)
        crm.log_activity(wl_a, user=self.user, kind=ActivityType.NOTE, body="A note")
        self.assertEqual(
            Activity.objects.filter(business=self.biz, workspace=self.ws_a,
                                    kind=ActivityType.NOTE).count(), 1)
        # Nothing leaks into workspace B's timeline.
        self.assertEqual(Activity.objects.filter(business=self.biz, workspace=self.ws_b).count(), 0)
        wl_b = crm.get_or_create_lead(self.ws_b, self.biz)
        self.assertIsNone(wl_b.assigned_to)

    def test_tags_isolated_per_workspace(self):
        tag_a = Tag.objects.create(name="Priority", workspace=self.ws_a)
        wl_a = crm.get_or_create_lead(self.ws_a, self.biz)
        crm.add_tag(wl_a, tag_a, user=self.user)
        in_b = Business.objects.with_workspace_state(self.ws_b).get(pk=self.biz.pk)
        self.assertEqual(list(in_b.effective_tags), [])


class LazyLeadStateTests(TestCase):
    def setUp(self):
        # A plain member: their only workspace is self.ws (admins would also see the
        # migration-seeded default workspace, which would win the active-workspace pick).
        self.user = User.objects.create_user("rep@example.com", "pw12345678")
        self.ws = make_workspace(members=[self.user])
        self.biz = make_business(name="Untouched", international_phone="+1 555")
        self.client.force_login(self.user)

    def test_untouched_lead_has_no_workspacelead(self):
        self.assertEqual(WorkspaceLead.objects.filter(business=self.biz).count(), 0)

    def test_untouched_lead_listed_as_new(self):
        resp = self.client.get(reverse("scraper:leads_table"))
        self.assertContains(resp, "Untouched")
        self.assertContains(resp, 'value="new" selected')

    def test_action_materialises_one_workspacelead(self):
        self.client.post(reverse("scraper:lead_assign", args=[self.biz.pk]), {"assignee": "me"})
        self.assertEqual(
            WorkspaceLead.objects.filter(business=self.biz, workspace=self.ws).count(), 1)


class MembershipAccessTests(TestCase):
    def setUp(self):
        self.member = User.objects.create_user("member@example.com", "pw12345678")
        self.outsider = User.objects.create_user("out@example.com", "pw12345678")
        self.admin = User.objects.create_user(
            "admin@example.com", "pw12345678", role="admin", is_staff=True, is_superuser=True)
        self.ws = make_workspace(name="Alpha", members=[self.member])

    def test_non_member_without_workspace_is_bounced(self):
        self.client.force_login(self.outsider)
        resp = self.client.get(reverse("scraper:leads"))
        self.assertRedirects(resp, reverse("scraper:no_workspace"))

    def test_member_can_view_leads(self):
        make_business(name="X")
        self.client.force_login(self.member)
        resp = self.client.get(reverse("scraper:leads"))
        self.assertEqual(resp.status_code, 200)

    def test_member_can_add_and_remove_members(self):
        self.client.force_login(self.member)
        self.client.post(reverse("scraper:workspace_add_member", args=[self.ws.pk]),
                         {"user": self.outsider.pk})
        self.assertTrue(
            WorkspaceMembership.objects.filter(workspace=self.ws, user=self.outsider).exists())
        self.client.post(
            reverse("scraper:workspace_remove_member", args=[self.ws.pk, self.outsider.pk]))
        self.assertFalse(
            WorkspaceMembership.objects.filter(workspace=self.ws, user=self.outsider).exists())

    def test_only_admin_creates_workspace(self):
        self.client.force_login(self.member)
        self.client.post(reverse("scraper:workspace_create"), {"name": "Nope"})
        self.assertFalse(Workspace.objects.filter(name="Nope").exists())
        self.client.force_login(self.admin)
        self.client.post(reverse("scraper:workspace_create"), {"name": "Yes WS"})
        self.assertTrue(Workspace.objects.filter(name="Yes WS").exists())


class WorkspaceSwitchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("rep@example.com", "pw12345678")
        self.ws_a = make_workspace(name="Alpha", members=[self.user])
        self.ws_b = make_workspace(name="Beta", members=[self.user])
        self.biz = make_business(name="Cafe", international_phone="+1 555")
        self.client.force_login(self.user)

    def test_switch_changes_which_funnel_is_shown(self):
        wl_a = crm.get_or_create_lead(self.ws_a, self.biz)
        crm.change_status(wl_a, LeadStatus.WON, user=self.user)

        self.client.post(reverse("scraper:workspace_switch"), {"workspace": self.ws_a.pk})
        resp = self.client.get(reverse("scraper:leads_table"))
        self.assertContains(resp, 'value="won" selected')

        self.client.post(reverse("scraper:workspace_switch"), {"workspace": self.ws_b.pk})
        resp = self.client.get(reverse("scraper:leads_table"))
        self.assertContains(resp, 'value="new" selected')
        self.assertNotContains(resp, 'value="won" selected')

    def test_cannot_switch_to_unjoined_workspace(self):
        other = make_workspace(name="Gamma")  # user is not a member
        self.client.post(reverse("scraper:workspace_switch"), {"workspace": other.pk})
        session_ws = self.client.session.get("active_workspace_id")
        self.assertNotEqual(session_ws, other.pk)
