"""Role helpers and view decorators."""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

def user_is_admin(user):
    """True for superusers and users with the Admin role."""
    if not getattr(user, "is_authenticated", False):
        return False
    return bool(getattr(user, "is_admin", False))


def admin_required(view):
    """Require an authenticated admin; viewers are bounced to the dashboard."""

    @wraps(view)
    @login_required
    def _wrapped(request, *args, **kwargs):
        if not user_is_admin(request.user):
            messages.error(request, "That action needs an admin role.")
            return redirect("scraper:dashboard")
        return view(request, *args, **kwargs)

    return _wrapped
