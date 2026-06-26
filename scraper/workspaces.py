"""Active-workspace resolution, membership helpers, and view decorator.

Funnel views call :func:`get_active_workspace` (or use the
:func:`workspace_member_required` decorator, which stashes it on
``request.workspace``) to scope everything to the workspace the user is
currently looking at. App admins can act in any workspace; everyone else only
in workspaces they're a member of.
"""

from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .access import user_is_admin
from .models import Workspace, WorkspaceMembership

SESSION_KEY = "active_workspace_id"


def user_workspaces(user):
    """Workspaces this user may act in. Admins see all; others, their memberships."""
    if not getattr(user, "is_authenticated", False):
        return Workspace.objects.none()
    if user_is_admin(user):
        return Workspace.objects.all()
    return user.workspaces.all()


def can_access(user, workspace):
    """True if ``user`` may work ``workspace`` (member, or app admin)."""
    if workspace is None or not getattr(user, "is_authenticated", False):
        return False
    if user_is_admin(user):
        return True
    return WorkspaceMembership.objects.filter(workspace=workspace, user=user).exists()


def get_active_workspace(request):
    """Resolve the workspace for this request, caching it on the request.

    Honours the session pick when the user may access it, else falls back to the
    user's default/first available workspace (persisting the choice). Returns
    ``None`` when the user has no workspace available at all.
    """
    if hasattr(request, "_active_workspace"):
        return request._active_workspace

    user = request.user
    ws = None
    ws_id = request.session.get(SESSION_KEY)
    if ws_id:
        ws = Workspace.objects.filter(pk=ws_id).first()
        if ws is not None and not can_access(user, ws):
            ws = None
    if ws is None:
        ws = user_workspaces(user).order_by("-is_default", "name").first()
        if ws is not None:
            request.session[SESSION_KEY] = ws.pk

    request._active_workspace = ws
    return ws


def workspace_members(workspace):
    """Active users who belong to ``workspace`` (for assignment dropdowns)."""
    if workspace is None:
        return get_user_model().objects.none()
    return workspace.members.filter(is_active=True).order_by("first_name", "email")


def workspace_member_required(view):
    """Require an active workspace the user may use; stash it on ``request.workspace``."""

    @wraps(view)
    @login_required
    def _wrapped(request, *args, **kwargs):
        ws = get_active_workspace(request)
        if ws is None:
            messages.info(
                request,
                "You're not part of any workspace yet — ask an admin to add you.",
            )
            return redirect("scraper:no_workspace")
        request.workspace = ws
        return view(request, *args, **kwargs)

    return _wrapped
