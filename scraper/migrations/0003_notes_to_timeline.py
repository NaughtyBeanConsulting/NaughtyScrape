"""Convert each lead's legacy free-text ``notes`` into a timeline note Activity.

The ``Business.notes`` column is left in place (deprecated) so nothing is lost;
this just seeds the new Activity timeline from whatever was already written.
The note's ``created_at`` is backdated to the lead's ``last_updated`` so the
timeline reads in a sensible order, and ``last_activity_at`` is primed.
"""

from django.db import migrations


def notes_to_activities(apps, schema_editor):
    Business = apps.get_model("scraper", "Business")
    Activity = apps.get_model("scraper", "Activity")

    for biz in Business.objects.exclude(notes="").iterator():
        body = (biz.notes or "").strip()
        if not body:
            continue
        activity = Activity.objects.create(
            business=biz, user=None, kind="note", body=body, metadata={"migrated": True},
        )
        # auto_now_add forced created_at=now(); backdate it to the lead's
        # last_updated so migrated notes sort before brand-new entries.
        Activity.objects.filter(pk=activity.pk).update(created_at=biz.last_updated)
        Business.objects.filter(pk=biz.pk).update(last_activity_at=biz.last_updated)


def unconvert(apps, schema_editor):
    # The original text still lives in Business.notes, so removing the seeded
    # note activities is a clean reverse.
    Activity = apps.get_model("scraper", "Activity")
    Activity.objects.filter(kind="note", metadata__migrated=True).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("scraper", "0002_tag_task_business_assigned_to_and_more"),
    ]

    operations = [
        migrations.RunPython(notes_to_activities, unconvert),
    ]
