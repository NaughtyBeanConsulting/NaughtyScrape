"""Template context processors for global nav data."""

from django.utils import timezone

from .access import user_is_admin
from .models import Business, CrawlJob, JobStatus, Task


def nav_counts(request):
    # Avoid DB hits on the login page / for anonymous users.
    if not getattr(request.user, "is_authenticated", False):
        return {"is_app_admin": False}
    today = timezone.localdate()
    my_open = Task.objects.filter(assigned_to=request.user, is_done=False)
    return {
        "nav_total_leads": Business.objects.count(),
        "nav_active_jobs": CrawlJob.objects.filter(
            status__in=[JobStatus.PENDING, JobStatus.RUNNING]
        ).count(),
        # Tasks needing attention today drive the "My Work" nav badge.
        "nav_my_due_count": my_open.filter(due_date__lte=today).count(),
        "is_app_admin": user_is_admin(request.user),
    }
