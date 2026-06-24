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

    path("leads/", views.leads_list, name="leads"),
    path("leads/table/", views.leads_table, name="leads_table"),
    path("leads/export.csv", views.leads_export, name="leads_export"),
    path("leads/enrich/", views.leads_enrich, name="leads_enrich"),
    path("leads/<int:pk>/", views.lead_detail, name="lead_detail"),
    path("leads/<int:pk>/status/", views.lead_update_status, name="lead_status"),
    path("leads/<int:pk>/notes/", views.lead_update_notes, name="lead_notes"),
    path("leads/<int:pk>/enrich/", views.lead_enrich_one, name="lead_enrich"),

    path("team/", views.team_list, name="team"),
    path("team/create/", views.team_create, name="team_create"),
    path("team/<int:pk>/role/", views.team_set_role, name="team_role"),
    path("team/<int:pk>/toggle/", views.team_toggle_active, name="team_toggle"),
]
