"""Finalise the workspace split.

Now that 0005 has backfilled, make the ``workspace`` FKs non-null, switch tags
to per-workspace uniqueness, and drop the per-lead funnel fields/indexes from
``Business`` (they now live on ``WorkspaceLead``).
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scraper', '0005_default_workspace_backfill'),
    ]

    operations = [
        # --- workspace FKs become required ---
        migrations.AlterField(
            model_name='tag',
            name='workspace',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tags', to='scraper.workspace'),
        ),
        migrations.AlterField(
            model_name='activity',
            name='workspace',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='activities', to='scraper.workspace'),
        ),
        migrations.AlterField(
            model_name='task',
            name='workspace',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='tasks', to='scraper.workspace'),
        ),
        migrations.AlterField(
            model_name='leadassignment',
            name='workspace',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lead_assignments', to='scraper.workspace'),
        ),
        # --- tags: per-workspace uniqueness ---
        migrations.AlterField(
            model_name='tag',
            name='name',
            field=models.CharField(max_length=64),
        ),
        migrations.AlterField(
            model_name='tag',
            name='slug',
            field=models.SlugField(blank=True, max_length=80),
        ),
        migrations.AlterUniqueTogether(
            name='tag',
            unique_together={('workspace', 'name'), ('workspace', 'slug')},
        ),
        # --- drop funnel state from Business (moved to WorkspaceLead) ---
        migrations.RemoveIndex(
            model_name='business',
            name='scraper_bus_status_c4b670_idx',
        ),
        migrations.RemoveIndex(
            model_name='business',
            name='scraper_bus_assigne_438f97_idx',
        ),
        migrations.RemoveField(
            model_name='business',
            name='tags',
        ),
        migrations.RemoveField(
            model_name='business',
            name='assigned_to',
        ),
        migrations.RemoveField(
            model_name='business',
            name='status',
        ),
        migrations.RemoveField(
            model_name='business',
            name='contacted_at',
        ),
        migrations.RemoveField(
            model_name='business',
            name='last_activity_at',
        ),
    ]
