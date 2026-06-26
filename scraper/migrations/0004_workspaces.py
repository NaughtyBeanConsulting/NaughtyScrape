"""Introduce workspaces: new models + nullable workspace FKs.

This is the additive half of the multi-workspace migration. It leaves the
existing per-lead funnel fields on ``Business`` in place and the new
``workspace`` FKs nullable so 0005 can backfill before 0006 finalises.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scraper', '0003_notes_to_timeline'),
    ]

    operations = [
        migrations.CreateModel(
            name='Workspace',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120)),
                ('slug', models.SlugField(blank=True, max_length=140, unique=True)),
                ('description', models.CharField(blank=True, max_length=255)),
                ('is_default', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='WorkspaceMembership',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('joined_at', models.DateTimeField(auto_now_add=True)),
                ('added_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='workspace_memberships', to=settings.AUTH_USER_MODEL)),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='memberships', to='scraper.workspace')),
            ],
            options={
                'ordering': ['user__first_name', 'user__email'],
                'unique_together': {('workspace', 'user')},
            },
        ),
        migrations.AddField(
            model_name='workspace',
            name='members',
            field=models.ManyToManyField(related_name='workspaces', through='scraper.WorkspaceMembership', through_fields=('workspace', 'user'), to=settings.AUTH_USER_MODEL),
        ),
        migrations.CreateModel(
            name='WorkspaceLead',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('new', 'New'), ('contacted', 'Contacted'), ('qualified', 'Qualified'), ('won', 'Won'), ('lost', 'Lost'), ('not_a_fit', 'Not a fit')], db_index=True, default='new', max_length=16)),
                ('contacted_at', models.DateTimeField(blank=True, null=True)),
                ('last_activity_at', models.DateTimeField(blank=True, db_index=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('assigned_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_leads', to=settings.AUTH_USER_MODEL)),
                ('business', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='workspace_leads', to='scraper.business')),
                ('tags', models.ManyToManyField(blank=True, related_name='leads', to='scraper.tag')),
                ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='leads', to='scraper.workspace')),
            ],
            options={
                'unique_together': {('workspace', 'business')},
                'indexes': [
                    models.Index(fields=['workspace', 'status'], name='ws_lead_ws_status_idx'),
                    models.Index(fields=['workspace', 'assigned_to'], name='ws_lead_ws_assignee_idx'),
                ],
            },
        ),
        migrations.AddField(
            model_name='tag',
            name='workspace',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='tags', to='scraper.workspace'),
        ),
        migrations.AddField(
            model_name='activity',
            name='workspace',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='activities', to='scraper.workspace'),
        ),
        migrations.AddField(
            model_name='task',
            name='workspace',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='tasks', to='scraper.workspace'),
        ),
        migrations.AddField(
            model_name='leadassignment',
            name='workspace',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='lead_assignments', to='scraper.workspace'),
        ),
    ]
