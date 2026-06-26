"""Backfill a default workspace and move existing funnel state into it.

Creates a single "Naughty Bean" workspace, makes every user a member, stamps
all existing tags/activities/tasks/assignments with it, and materialises a
``WorkspaceLead`` for each business that has any funnel state (anything beyond a
pristine New/unassigned lead). Pristine leads stay lazy (no row) — consistent
with how new workspace state is created on first touch.
"""

from django.db import migrations

DEFAULT_NAME = "Naughty Bean"
DEFAULT_SLUG = "naughty-bean"


def forwards(apps, schema_editor):
    Workspace = apps.get_model("scraper", "Workspace")
    Membership = apps.get_model("scraper", "WorkspaceMembership")
    WorkspaceLead = apps.get_model("scraper", "WorkspaceLead")
    Business = apps.get_model("scraper", "Business")
    Tag = apps.get_model("scraper", "Tag")
    Activity = apps.get_model("scraper", "Activity")
    Task = apps.get_model("scraper", "Task")
    LeadAssignment = apps.get_model("scraper", "LeadAssignment")
    User = apps.get_model("scraper", "User")

    ws = Workspace.objects.create(
        name=DEFAULT_NAME, slug=DEFAULT_SLUG, is_default=True,
        description="Default workspace (rename me).",
    )

    for user in User.objects.all():
        Membership.objects.get_or_create(workspace=ws, user=user)

    # Everything that was global is now this workspace's.
    Tag.objects.update(workspace=ws)
    Activity.objects.update(workspace=ws)
    Task.objects.update(workspace=ws)
    LeadAssignment.objects.update(workspace=ws)

    for biz in Business.objects.all().iterator():
        has_state = bool(
            biz.status != "new"
            or biz.assigned_to_id
            or biz.contacted_at
            or biz.last_activity_at
            or biz.tags.exists()
            or biz.activities.exists()
            or biz.tasks.exists()
        )
        if not has_state:
            continue
        wl = WorkspaceLead.objects.create(
            workspace=ws,
            business=biz,
            status=biz.status,
            assigned_to_id=biz.assigned_to_id,
            contacted_at=biz.contacted_at,
            last_activity_at=biz.last_activity_at,
        )
        tag_ids = list(biz.tags.values_list("pk", flat=True))
        if tag_ids:
            wl.tags.set(tag_ids)


def backwards(apps, schema_editor):
    Workspace = apps.get_model("scraper", "Workspace")
    WorkspaceLead = apps.get_model("scraper", "WorkspaceLead")
    Tag = apps.get_model("scraper", "Tag")
    Activity = apps.get_model("scraper", "Activity")
    Task = apps.get_model("scraper", "Task")
    LeadAssignment = apps.get_model("scraper", "LeadAssignment")

    # Detach FKs first so deleting the workspace can't cascade real data away.
    for model in (Tag, Activity, Task, LeadAssignment):
        model.objects.update(workspace=None)
    WorkspaceLead.objects.all().delete()
    Workspace.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("scraper", "0004_workspaces"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
