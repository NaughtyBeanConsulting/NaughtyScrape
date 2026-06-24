"""Template context processors for global nav data."""

from .access import user_is_admin
from .models import Business, CrawlJob, JobStatus


def nav_counts(request):
    # Avoid DB hits on the login page / for anonymous users.
    if not getattr(request.user, "is_authenticated", False):
        return {"is_app_admin": False}
    return {
        "nav_total_leads": Business.objects.count(),
        "nav_active_jobs": CrawlJob.objects.filter(
            status__in=[JobStatus.PENDING, JobStatus.RUNNING]
        ).count(),
        "is_app_admin": user_is_admin(request.user),
    }
