from django.urls import path

from . import views

app_name = "scraper"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),

    path("search/", views.search_view, name="search"),

    path("jobs/", views.jobs_list, name="jobs"),
    path("jobs/<int:pk>/", views.job_detail, name="job_detail"),
    path("jobs/<int:pk>/progress/", views.job_progress, name="job_progress"),
    path("jobs/<int:pk>/cancel/", views.job_cancel, name="job_cancel"),

    path("work/", views.work, name="work"),

    path("leads/", views.leads_list, name="leads"),
    path("leads/table/", views.leads_table, name="leads_table"),
    path("leads/export.csv", views.leads_export, name="leads_export"),
    path("leads/enrich/", views.leads_enrich, name="leads_enrich"),
    path("leads/bulk/", views.leads_bulk, name="leads_bulk"),
    path("leads/<int:pk>/", views.lead_detail, name="lead_detail"),
    path("leads/<int:pk>/status/", views.lead_update_status, name="lead_status"),
    path("leads/<int:pk>/activity/", views.lead_add_activity, name="lead_activity"),
    path("leads/<int:pk>/assign/", views.lead_assign, name="lead_assign"),
    path("leads/<int:pk>/tag/", views.lead_add_tag, name="lead_add_tag"),
    path("leads/<int:pk>/tag/<int:tag_id>/remove/", views.lead_remove_tag, name="lead_remove_tag"),
    path("leads/<int:pk>/contact/", views.lead_add_contact, name="lead_add_contact"),
    path("leads/<int:pk>/contact/<int:contact_id>/delete/", views.lead_delete_contact, name="lead_delete_contact"),
    path("leads/<int:pk>/task/", views.lead_add_task, name="lead_add_task"),
    path("leads/<int:pk>/enrich/", views.lead_enrich_one, name="lead_enrich"),

    path("tags/create/", views.tag_create, name="tag_create"),

    path("tasks/", views.tasks_list, name="tasks"),
    path("tasks/<int:pk>/toggle/", views.task_toggle, name="task_toggle"),

    path("team/", views.team_list, name="team"),
    path("team/create/", views.team_create, name="team_create"),
    path("team/<int:pk>/role/", views.team_set_role, name="team_role"),
    path("team/<int:pk>/toggle/", views.team_toggle_active, name="team_toggle"),
]
