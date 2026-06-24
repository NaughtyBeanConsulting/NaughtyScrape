from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import (
    Activity,
    Business,
    Contact,
    CrawlJob,
    LeadAssignment,
    Tag,
    Task,
    User,
)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    ordering = ("email",)
    list_display = ("email", "first_name", "last_name", "role", "is_staff", "is_active")
    list_filter = ("role", "is_staff", "is_active", "is_superuser")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal", {"fields": ("first_name", "last_name")}),
        ("Role & permissions", {"fields": (
            "role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions",
        )}),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ("email", "password1", "password2", "role"),
        }),
    )


@admin.register(CrawlJob)
class CrawlJobAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "status", "query", "results_found",
                    "new_count", "processed", "total", "created_at")
    list_filter = ("kind", "status")
    search_fields = ("query",)
    readonly_fields = ("created_at", "started_at", "finished_at", "log")


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "country", "status", "enrichment_status",
                    "primary_email", "phone_display", "rating", "first_seen")
    list_filter = ("status", "enrichment_status", "country")
    search_fields = ("name", "formatted_address", "website")
    readonly_fields = ("place_id", "first_seen", "last_updated")

    @admin.display(description="phone")
    def phone_display(self, obj):
        return obj.international_phone or obj.national_phone


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "color", "created_at")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Contact)
class ContactAdmin(admin.ModelAdmin):
    list_display = ("name", "business", "title", "email", "phone", "is_primary")
    list_filter = ("is_primary",)
    search_fields = ("name", "email", "business__name")
    raw_id_fields = ("business", "created_by")


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ("id", "business", "kind", "user", "created_at")
    list_filter = ("kind",)
    search_fields = ("body", "business__name")
    raw_id_fields = ("business", "user")
    readonly_fields = ("created_at",)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "business", "assigned_to", "due_date", "is_done")
    list_filter = ("is_done",)
    search_fields = ("title", "business__name")
    raw_id_fields = ("business", "assigned_to", "created_by")


@admin.register(LeadAssignment)
class LeadAssignmentAdmin(admin.ModelAdmin):
    list_display = ("id", "business", "user", "assigned_by", "created_at")
    search_fields = ("business__name",)
    raw_id_fields = ("business", "user", "assigned_by")
    readonly_fields = ("created_at",)
