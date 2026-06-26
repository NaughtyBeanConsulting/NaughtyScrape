"""CRM mutations: the single place that changes a lead and records why.

Every state change a salesperson makes (status, assignment, tag, task, logged
touch) flows through here so it lands as a timeline ``Activity`` and keeps the
denormalised bookkeeping on the ``WorkspaceLead`` (``last_activity_at``,
``contacted_at``) in sync.

The unit of work is a ``WorkspaceLead`` (``wl``) — one workspace's funnel state
for one shared ``Business``. Views resolve it with :func:`get_or_create_lead`
(lazy creation) and then call these helpers instead of poking fields directly.
"""

from django.utils import timezone

from scraper.models import (
    Activity,
    ActivityType,
    CONTACT_ACTIVITY_TYPES,
    LeadAssignment,
    LeadStatus,
    Task,
    WorkspaceLead,
)


# ---------------------------------------------------------------------------
# Lazy per-workspace funnel state
# ---------------------------------------------------------------------------
def get_or_create_lead(workspace, business):
    """Return the ``WorkspaceLead`` for ``(workspace, business)``, creating it.

    A lead is untouched in a workspace until someone acts on it; this is the
    single entry point that materialises that state on first touch.
    """
    wl, _ = WorkspaceLead.objects.get_or_create(workspace=workspace, business=business)
    return wl


# ---------------------------------------------------------------------------
# Timeline
# ---------------------------------------------------------------------------
def log_activity(wl, *, user=None, kind=ActivityType.NOTE, body="", **metadata):
    """Record a timeline entry and bump the lead's ``last_activity_at``.

    Logging an outreach touch (call/email/whatsapp/meeting) also stamps
    ``contacted_at`` the first time, so "first contacted" stays meaningful.
    """
    activity = Activity.objects.create(
        workspace=wl.workspace, business=wl.business,
        user=user, kind=kind, body=body, metadata=metadata or {},
    )
    fields = ["last_activity_at"]
    wl.last_activity_at = activity.created_at
    if kind in CONTACT_ACTIVITY_TYPES and not wl.contacted_at:
        wl.contacted_at = activity.created_at
        fields.append("contacted_at")
    wl.save(update_fields=fields)
    return activity


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
def change_status(wl, new_status, *, user=None):
    """Move a lead to ``new_status``; log it and return True if it changed."""
    valid = {c[0] for c in LeadStatus.choices}
    if new_status not in valid or new_status == wl.status:
        return False

    old_status = wl.status
    wl.status = new_status
    fields = ["status"]
    if new_status == LeadStatus.CONTACTED and not wl.contacted_at:
        wl.contacted_at = timezone.now()
        fields.append("contacted_at")
    wl.save(update_fields=fields)

    old_label = dict(LeadStatus.choices).get(old_status, old_status)
    new_label = dict(LeadStatus.choices).get(new_status, new_status)
    log_activity(
        wl, user=user, kind=ActivityType.STATUS,
        body=f"{old_label} → {new_label}",
        old_status=old_status, new_status=new_status,
    )
    return True


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------
def assign_lead(wl, assignee, *, by=None):
    """Set the current owner, log the hand-off, and keep an assignment record.

    ``assignee`` may be ``None`` to unassign. Returns True when it changed.
    """
    if wl.assigned_to_id == (assignee.pk if assignee else None):
        return False

    wl.assigned_to = assignee
    wl.save(update_fields=["assigned_to"])
    LeadAssignment.objects.create(
        workspace=wl.workspace, business=wl.business, user=assignee, assigned_by=by
    )

    if assignee:
        body = f"Assigned to {assignee.email}"
    else:
        body = "Unassigned"
    log_activity(
        wl, user=by, kind=ActivityType.ASSIGNMENT, body=body,
        assignee_id=assignee.pk if assignee else None,
    )
    return True


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
def add_tag(wl, tag, *, user=None):
    """Apply a tag if not already present; log it. Returns True when added."""
    if wl.tags.filter(pk=tag.pk).exists():
        return False
    wl.tags.add(tag)
    log_activity(
        wl, user=user, kind=ActivityType.TAG,
        body=f"Tagged “{tag.name}”", tag_id=tag.pk, action="add",
    )
    return True


def remove_tag(wl, tag, *, user=None):
    if not wl.tags.filter(pk=tag.pk).exists():
        return False
    wl.tags.remove(tag)
    log_activity(
        wl, user=user, kind=ActivityType.TAG,
        body=f"Removed tag “{tag.name}”", tag_id=tag.pk, action="remove",
    )
    return True


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
def create_task(wl, *, title, assignee=None, by=None, due_date=None):
    """Create a follow-up task on a lead and log it to the timeline."""
    task = Task.objects.create(
        workspace=wl.workspace, business=wl.business, title=title,
        assigned_to=assignee, created_by=by, due_date=due_date,
    )
    due = f" (due {due_date:%d %b})" if due_date else ""
    log_activity(
        wl, user=by, kind=ActivityType.TASK,
        body=f"Task created: {title}{due}", task_id=task.pk, action="created",
    )
    return task


def complete_task(task, *, user=None, done=True):
    """Toggle a task done/open, stamping completion and logging the change."""
    if task.is_done == done:
        return task
    task.is_done = done
    task.completed_at = timezone.now() if done else None
    task.save(update_fields=["is_done", "completed_at"])
    verb = "completed" if done else "reopened"
    wl = get_or_create_lead(task.workspace, task.business)
    log_activity(
        wl, user=user, kind=ActivityType.TASK,
        body=f"Task {verb}: {task.title}", task_id=task.pk, action=verb,
    )
    return task
