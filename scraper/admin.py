from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import Business, CrawlJob, User


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
