"""Views for the NaughtyScrape lead scraper UI (htmx + Alpine + Tailwind).

Funnel pages are scoped to the *active workspace* (``request.workspace``, set by
``workspace_member_required``). The shared ``Business`` pool is global; each
workspace overlays its own funnel state via ``WorkspaceLead`` — see
``Business.with_workspace_state`` and ``services/crm.py``.
"""

import csv

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.http import require_POST

from .access import admin_required
from .constants import EXPANSION_QUERIES, QUERY_PRESETS, SEED_CITIES
from .forms import ContactForm, NewUserForm, TagForm, TaskForm
from .models import (
    Activity,
    Business,
    COMPOSER_ACTIVITY_TYPES,
    Contact,
    CrawlJob,
    EnrichmentStatus,
    JobStatus,
    LeadStatus,
    Role,
    Tag,
    TAG_COLORS,
    Task,
    Workspace,
    WorkspaceLead,
    WorkspaceMembership,
)
from .services import crawler, crm
from .workspaces import (
    can_access,
    get_active_workspace,
    user_workspaces,
    workspace_member_required,
    workspace_members,
    SESSION_KEY,
)

PAGE_SIZE = 25


def _parse_due_date(raw):
    """Parse an ISO date string from a form; return a date or None."""
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return parse_date(raw)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Lead filtering (shared by list, htmx table, and CSV export) — workspace-scoped
# ---------------------------------------------------------------------------
def filter_leads(request, workspace):
    qs = Business.objects.with_workspace_state(workspace)
    params = request.GET

    q = params.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(formatted_address__icontains=q)
            | Q(website__icontains=q)
            | Q(contacts__name__icontains=q)
            | Q(contacts__email__icontains=q)
        ).distinct()

    # --- per-workspace status (untouched leads read as New / null) ---
    status = params.get("status", "").strip()
    if status:
        if status == LeadStatus.NEW:
            qs = qs.filter(Q(ws_status=LeadStatus.NEW) | Q(ws_status__isnull=True))
        else:
            qs = qs.filter(ws_status=status)

    enrichment = params.get("enrichment", "").strip()
    if enrichment:
        qs = qs.filter(enrichment_status=enrichment)

    country = params.get("country", "").strip()
    if country:
        qs = qs.filter(country=country)

    # --- CRM: ownership (per workspace) ---
    assigned = params.get("assigned", "").strip()
    if assigned == "me" and request.user.is_authenticated:
        qs = qs.filter(ws_assigned_to_id=request.user.pk)
    elif assigned == "none":
        qs = qs.filter(ws_assigned_to_id__isnull=True)
    elif assigned.isdigit():
        qs = qs.filter(ws_assigned_to_id=int(assigned))

    # --- CRM: tag (per workspace) ---
    tag = params.get("tag", "").strip()
    if tag:
        qs = qs.filter(
            workspace_leads__workspace=workspace, workspace_leads__tags__slug=tag
        ).distinct()

    # --- CRM: quick work-queue views ---
    view = params.get("view", "").strip()
    if view == "mine" and request.user.is_authenticated:
        qs = qs.filter(ws_assigned_to_id=request.user.pk)
    elif view == "ready":
        # Fresh (New/untouched) + reachable + not already someone else's job.
        qs = qs.filter(Q(ws_status=LeadStatus.NEW) | Q(ws_status__isnull=True)).filter(
            Q(international_phone__gt="") | Q(national_phone__gt="") | ~Q(emails=[])
        )
        if request.user.is_authenticated:
            qs = qs.filter(
                Q(ws_assigned_to_id__isnull=True) | Q(ws_assigned_to_id=request.user.pk)
            )

    if params.get("has_email") == "1":
        qs = qs.exclude(emails=[])
    if params.get("has_website") == "1":
        qs = qs.exclude(website="")

    sort = params.get("sort", "-first_seen")
    allowed_sorts = {
        "-first_seen", "first_seen", "name", "-name",
        "-rating", "rating", "-user_ratings_total",
        "-last_activity_at", "last_activity_at",
    }
    if sort not in allowed_sorts:
        sort = "-first_seen"
    # last_activity_at is a workspace annotation; nulls sort last either way.
    if sort == "-last_activity_at":
        return qs.order_by(F("ws_last_activity_at").desc(nulls_last=True))
    if sort == "last_activity_at":
        return qs.order_by(F("ws_last_activity_at").asc(nulls_last=True))
    return qs.order_by(sort)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@workspace_member_required
def dashboard(request):
    ws = request.workspace
    leads = Business.objects.all()
    total = leads.count()

    # Per-workspace status counts. Untouched leads (no WorkspaceLead) are New, so
    # New = whole pool minus everything that's been advanced past New here.
    wl_counts = {
        row["status"]: row["n"]
        for row in WorkspaceLead.objects.filter(workspace=ws)
        .values("status").annotate(n=Count("id"))
    }
    advanced = sum(n for s, n in wl_counts.items() if s != LeadStatus.NEW)
    status_counts = {s.value: wl_counts.get(s.value, 0) for s in LeadStatus}
    status_counts[LeadStatus.NEW.value] = max(0, total - advanced)

    by_status = [
        {"value": s.value, "label": s.label, "count": status_counts.get(s.value, 0)}
        for s in LeadStatus
    ]

    # Sales funnel: cumulative "reached this stage or later" along the pipeline.
    funnel_stages = [
        (LeadStatus.NEW, "bg-sky-500"),
        (LeadStatus.CONTACTED, "bg-amber-500"),
        (LeadStatus.QUALIFIED, "bg-violet-500"),
        (LeadStatus.WON, "bg-emerald-500"),
    ]
    reached, running = [], 0
    for status, _color in reversed(funnel_stages):
        running += status_counts.get(status.value, 0)
        reached.append(running)
    reached.reverse()

    pipeline_top = reached[0] if reached else 0
    funnel, prev = [], None
    for (status, color), reached_count in zip(funnel_stages, reached):
        funnel.append({
            "value": status.value,
            "label": status.label,
            "color": color,
            "reached": reached_count,
            "in_stage": status_counts.get(status.value, 0),
            "pct_top": round(reached_count / pipeline_top * 100) if pipeline_top else 0,
            "conv_from_prev": round(reached_count / prev * 100) if prev else None,
        })
        prev = reached_count

    won_count = status_counts.get(LeadStatus.WON.value, 0)
    funnel_metrics = {
        "pipeline": pipeline_top,
        "won": won_count,
        "overall_conv": round(won_count / pipeline_top * 100) if pipeline_top else 0,
        "lost": status_counts.get(LeadStatus.LOST.value, 0),
        "not_a_fit": status_counts.get(LeadStatus.NOT_A_FIT.value, 0),
    }

    top_countries = list(
        leads.exclude(country="")
        .values("country")
        .annotate(n=Count("id"))
        .order_by("-n")[:8]
    )
    context = {
        "total": total,
        "with_email": leads.exclude(emails=[]).count(),
        "with_website": leads.exclude(website="").count(),
        "not_enriched": leads.exclude(website="").exclude(
            enrichment_status=EnrichmentStatus.DONE
        ).count(),
        "by_status": by_status,
        "funnel": funnel,
        "funnel_metrics": funnel_metrics,
        "top_countries": top_countries,
        "recent_jobs": CrawlJob.objects.all()[:6],
        "active_jobs": CrawlJob.objects.filter(
            status__in=[JobStatus.PENDING, JobStatus.RUNNING]
        ).count(),
        "has_api_key": bool(settings.GOOGLE_MAPS_API_KEY),
    }
    return render(request, "scraper/dashboard.html", context)


# ---------------------------------------------------------------------------
# Search (global, admin-run — fills the shared pool)
# ---------------------------------------------------------------------------
@admin_required
def search_view(request):
    if request.method == "POST":
        query = request.POST.get("query", "").strip()
        raw_locations = request.POST.get("locations", "")
        locations = [ln.strip() for ln in raw_locations.splitlines() if ln.strip()]
        language = request.POST.get("language", "").strip()
        region = request.POST.get("region", "").strip()
        auto_expand = request.POST.get("auto_expand") == "1"
        try:
            max_pages = int(request.POST.get("max_pages", 3))
        except (TypeError, ValueError):
            max_pages = 3

        if not query and not locations and not auto_expand:
            messages.error(request, "Enter a query and at least one location.")
        else:
            job = crawler.enqueue_search(
                query, locations, language=language, region=region,
                max_pages=max_pages, auto_expand=auto_expand,
            )
            messages.success(
                request,
                f"Queued search across {len(locations) or 1} location(s)"
                f"{' with auto-expand' if auto_expand else ''}. "
                "It will run in the background.",
            )
            return redirect("scraper:job_detail", pk=job.pk)

    context = {
        "seed_cities": SEED_CITIES,
        "seed_cities_text": "\n".join(SEED_CITIES),
        "query_presets": QUERY_PRESETS,
        "expansion_count": len(EXPANSION_QUERIES),
    }
    return render(request, "scraper/search.html", context)


# ---------------------------------------------------------------------------
# Jobs (global)
# ---------------------------------------------------------------------------
@login_required
def jobs_list(request):
    jobs = CrawlJob.objects.all()
    paginator = Paginator(jobs, 20)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "scraper/jobs.html", {"page": page})


@login_required
def job_detail(request, pk):
    job = get_object_or_404(CrawlJob, pk=pk)
    return render(request, "scraper/job_detail.html", {"job": job})


@login_required
def job_progress(request, pk):
    """htmx partial — polled while a job is active to update progress + log."""
    job = get_object_or_404(CrawlJob, pk=pk)
    return render(request, "scraper/partials/_job_progress.html", {"job": job})


@admin_required
@require_POST
def job_cancel(request, pk):
    job = get_object_or_404(CrawlJob, pk=pk)
    if job.is_active:
        job.status = JobStatus.CANCELLED
        job.add_log("Cancellation requested.", level="warning", save=False)
        job.save(update_fields=["status", "log"])
        messages.info(request, f"Job #{job.pk} cancellation requested.")
    return redirect("scraper:job_detail", pk=job.pk)


# ---------------------------------------------------------------------------
# Leads
# ---------------------------------------------------------------------------
def _leads_context(request, ws):
    qs = filter_leads(request, ws)
    paginator = Paginator(qs, PAGE_SIZE)
    page = paginator.get_page(request.GET.get("page"))
    querydict = request.GET.copy()
    querydict.pop("page", None)
    countries = list(
        Business.objects.exclude(country="")
        .values_list("country", flat=True)
        .distinct()
        .order_by("country")
    )
    return {
        "page": page,
        "total_matched": paginator.count,
        "querystring": querydict.urlencode(),
        "countries": countries,
        "lead_statuses": LeadStatus.choices,
        "enrichment_statuses": EnrichmentStatus.choices,
        "filters": request.GET,
        "team_members": workspace_members(ws),
        "tags": Tag.objects.filter(workspace=ws),
        "tag_colors": TAG_COLORS,
        "active_view": request.GET.get("view", ""),
    }


@workspace_member_required
def leads_list(request):
    return render(request, "scraper/leads.html", _leads_context(request, request.workspace))


@workspace_member_required
def leads_table(request):
    """htmx partial — the leads table body + pagination (filtered)."""
    return render(
        request, "scraper/partials/_leads_table.html",
        _leads_context(request, request.workspace),
    )


@workspace_member_required
def lead_detail(request, pk):
    ws = request.workspace
    business = get_object_or_404(Business, pk=pk)
    wl = crm.get_or_create_lead(ws, business)
    activities = (
        Activity.objects.filter(business=business, workspace=ws)
        .select_related("user")[:200]
    )
    open_tasks = (
        Task.objects.filter(business=business, workspace=ws, is_done=False)
        .select_related("assigned_to")
    )
    done_tasks = (
        Task.objects.filter(business=business, workspace=ws, is_done=True)
        .select_related("assigned_to")[:10]
    )
    return render(request, "scraper/lead_detail.html", {
        "lead": business,
        "wl": wl,
        "lead_statuses": LeadStatus.choices,
        "activities": activities,
        "contacts": business.contacts.all(),
        "open_tasks": open_tasks,
        "done_tasks": done_tasks,
        "composer_types": [(t.value, t.label) for t in COMPOSER_ACTIVITY_TYPES],
        "team_members": workspace_members(ws),
        "all_tags": Tag.objects.filter(workspace=ws),
        "contact_form": ContactForm(),
        "task_form": TaskForm(workspace=ws),
    })


@workspace_member_required
@require_POST
def lead_update_status(request, pk):
    ws = request.workspace
    business = get_object_or_404(Business, pk=pk)
    wl = crm.get_or_create_lead(ws, business)
    # The select is named status-<pk> so it stays unambiguous inside the
    # multi-row bulk form; fall back to "status" for safety.
    new_status = request.POST.get(f"status-{pk}") or request.POST.get("status", "")
    crm.change_status(wl, new_status, user=request.user)
    return render(request, "scraper/partials/_status_select.html", {
        "lead": business, "status": wl.status, "lead_statuses": LeadStatus.choices,
    })


@workspace_member_required
@require_POST
def lead_add_activity(request, pk):
    """Log a timeline entry (note / call / email / whatsapp / meeting)."""
    ws = request.workspace
    business = get_object_or_404(Business, pk=pk)
    kind = request.POST.get("kind", "note")
    valid_kinds = {t.value for t in COMPOSER_ACTIVITY_TYPES}
    if kind not in valid_kinds:
        kind = "note"
    body = request.POST.get("body", "").strip()
    if not body:
        messages.error(request, "Write something before logging it.")
        return redirect("scraper:lead_detail", pk=business.pk)
    wl = crm.get_or_create_lead(ws, business)
    crm.log_activity(wl, user=request.user, kind=kind, body=body)
    messages.success(request, "Logged to the timeline.")
    return redirect("scraper:lead_detail", pk=business.pk)


@workspace_member_required
@require_POST
def lead_assign(request, pk):
    """Set (or clear) the owner of a single lead within this workspace."""
    ws = request.workspace
    business = get_object_or_404(Business, pk=pk)
    wl = crm.get_or_create_lead(ws, business)
    raw = request.POST.get("assignee", "").strip()
    assignee = None
    if raw == "me":
        assignee = request.user
    elif raw.isdigit():
        assignee = workspace_members(ws).filter(pk=int(raw)).first()
    crm.assign_lead(wl, assignee, by=request.user)
    messages.success(
        request,
        f"Assigned to {assignee.email}." if assignee else "Lead unassigned.",
    )
    return redirect("scraper:lead_detail", pk=business.pk)


@workspace_member_required
@require_POST
def lead_add_tag(request, pk):
    ws = request.workspace
    business = get_object_or_404(Business, pk=pk)
    wl = crm.get_or_create_lead(ws, business)
    tag_id = request.POST.get("tag", "").strip()
    tag = (
        Tag.objects.filter(pk=tag_id, workspace=ws).first()
        if tag_id.isdigit() else None
    )
    if tag:
        crm.add_tag(wl, tag, user=request.user)
    return redirect("scraper:lead_detail", pk=business.pk)


@workspace_member_required
@require_POST
def lead_remove_tag(request, pk, tag_id):
    ws = request.workspace
    business = get_object_or_404(Business, pk=pk)
    wl = crm.get_or_create_lead(ws, business)
    tag = Tag.objects.filter(pk=tag_id, workspace=ws).first()
    if tag:
        crm.remove_tag(wl, tag, user=request.user)
    return redirect("scraper:lead_detail", pk=business.pk)


@workspace_member_required
@require_POST
def lead_add_contact(request, pk):
    ws = request.workspace
    business = get_object_or_404(Business, pk=pk)
    form = ContactForm(request.POST)
    if form.is_valid():
        contact = form.save(commit=False)
        contact.business = business
        contact.created_by = request.user
        # Only one primary contact per lead.
        if contact.is_primary:
            business.contacts.update(is_primary=False)
        contact.save()
        wl = crm.get_or_create_lead(ws, business)
        crm.log_activity(
            wl, user=request.user, kind="contact",
            body=f"Added contact {contact.name}"
            + (f" ({contact.title})" if contact.title else ""),
            contact_id=contact.pk,
        )
        messages.success(request, f"Added contact {contact.name}.")
    else:
        messages.error(request, "Could not add contact — check the fields.")
    return redirect("scraper:lead_detail", pk=business.pk)


@workspace_member_required
@require_POST
def lead_delete_contact(request, pk, contact_id):
    business = get_object_or_404(Business, pk=pk)
    contact = get_object_or_404(Contact, pk=contact_id, business=business)
    name = contact.name
    contact.delete()
    messages.info(request, f"Removed contact {name}.")
    return redirect("scraper:lead_detail", pk=business.pk)


@workspace_member_required
@require_POST
def lead_add_task(request, pk):
    ws = request.workspace
    business = get_object_or_404(Business, pk=pk)
    form = TaskForm(request.POST, workspace=ws)
    if form.is_valid():
        data = form.cleaned_data
        wl = crm.get_or_create_lead(ws, business)
        crm.create_task(
            wl, title=data["title"], assignee=data.get("assigned_to"),
            by=request.user, due_date=data.get("due_date"),
        )
        messages.success(request, "Task added.")
    else:
        messages.error(request, "Give the task a title.")
    return redirect("scraper:lead_detail", pk=business.pk)


@admin_required
@require_POST
def lead_enrich_one(request, pk):
    business = get_object_or_404(Business, pk=pk)
    if not business.website:
        messages.error(request, f"{business.name} has no website to enrich.")
        return redirect("scraper:lead_detail", pk=business.pk)
    job = crawler.enqueue_enrich([business.pk])
    messages.success(request, "Enrichment queued.")
    return redirect("scraper:job_detail", pk=job.pk)


@admin_required
@require_POST
def leads_enrich(request):
    ids = request.POST.getlist("ids")
    ids = [int(i) for i in ids if i.isdigit()]
    job = crawler.enqueue_enrich(ids or None)
    scope = f"{len(ids)} selected" if ids else "all leads with a website"
    messages.success(request, f"Queued website enrichment for {scope}.")
    return redirect("scraper:job_detail", pk=job.pk)


@workspace_member_required
def leads_export(request):
    ws = request.workspace
    qs = filter_leads(request, ws)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="naughtyscrape-{ws.slug}-leads-{timezone.now():%Y%m%d-%H%M}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow([
        "Name", "Status", "Owner", "Tags", "Rating", "Reviews", "Phone", "Website",
        "Emails", "City", "Country", "Address", "Google Maps", "Facebook",
        "Instagram", "LinkedIn", "Primary type", "Last activity",
    ])
    for b in qs.iterator():
        socials = b.social_links or {}
        owner = b.effective_assignee
        writer.writerow([
            b.name, b.effective_status_display,
            owner.email if owner else "",
            ", ".join(t.name for t in b.effective_tags),
            b.rating or "", b.user_ratings_total,
            b.international_phone or b.national_phone, b.website,
            "; ".join(b.emails or []), b.city, b.country, b.formatted_address,
            b.google_maps_uri, socials.get("facebook", ""),
            socials.get("instagram", ""), socials.get("linkedin", ""),
            b.primary_type,
            b.effective_last_activity_at.strftime("%Y-%m-%d %H:%M")
            if b.effective_last_activity_at else "",
        ])
    return response


# ---------------------------------------------------------------------------
# Bulk actions (assign / status / tag / task), plus tag creation
# ---------------------------------------------------------------------------
@workspace_member_required
@require_POST
def leads_bulk(request):
    """Apply one action to a set of selected leads, then return to the list."""
    ws = request.workspace
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    action = request.POST.get("action", "").strip()
    back = request.POST.get("next") or "scraper:leads"

    if not ids:
        messages.error(request, "Select at least one lead first.")
        return redirect(back)

    businesses = list(Business.objects.filter(pk__in=ids))
    wls = [crm.get_or_create_lead(ws, b) for b in businesses]
    n = len(wls)

    if action == "assign":
        raw = request.POST.get("assignee", "").strip()
        assignee = None
        if raw == "me":
            assignee = request.user
        elif raw.isdigit():
            assignee = workspace_members(ws).filter(pk=int(raw)).first()
        for wl in wls:
            crm.assign_lead(wl, assignee, by=request.user)
        who = assignee.email if assignee else "nobody"
        messages.success(request, f"Assigned {n} lead(s) to {who}.")

    elif action == "status":
        new_status = request.POST.get("status", "").strip()
        changed = sum(
            1 for wl in wls if crm.change_status(wl, new_status, user=request.user)
        )
        messages.success(request, f"Updated status on {changed} lead(s).")

    elif action == "tag":
        tag = Tag.objects.filter(pk=request.POST.get("tag", ""), workspace=ws).first()
        if tag:
            added = sum(1 for wl in wls if crm.add_tag(wl, tag, user=request.user))
            messages.success(request, f"Tagged {added} lead(s) “{tag.name}”.")
        else:
            messages.error(request, "Pick a tag to apply.")

    elif action == "task":
        title = request.POST.get("task_title", "").strip()
        if not title:
            messages.error(request, "Give the task a title.")
            return redirect(back)
        raw = request.POST.get("assignee", "").strip()
        assignee = request.user if raw == "me" else (
            workspace_members(ws).filter(pk=int(raw)).first() if raw.isdigit() else None
        )
        due = _parse_due_date(request.POST.get("due_date"))
        for wl in wls:
            crm.create_task(wl, title=title, assignee=assignee, by=request.user, due_date=due)
        messages.success(request, f"Created a task on {n} lead(s).")

    else:
        messages.error(request, "Unknown bulk action.")

    return redirect(back)


@workspace_member_required
@require_POST
def tag_create(request):
    form = TagForm(request.POST, workspace=request.workspace)
    if form.is_valid():
        tag = form.save()
        messages.success(request, f"Created tag “{tag.name}”.")
    else:
        first_error = next(iter(form.errors.values()))[0]
        messages.error(request, f"Could not create tag: {first_error}")
    return redirect(request.POST.get("next") or "scraper:leads")


# ---------------------------------------------------------------------------
# Tasks (workspace-scoped)
# ---------------------------------------------------------------------------
def _filter_tasks(request, ws):
    qs = Task.objects.filter(workspace=ws).select_related("business", "assigned_to")
    params = request.GET

    scope = params.get("scope", "mine")
    if scope == "mine" and request.user.is_authenticated:
        qs = qs.filter(assigned_to=request.user)
    elif scope == "unassigned":
        qs = qs.filter(assigned_to__isnull=True)
    elif scope.isdigit():
        qs = qs.filter(assigned_to_id=int(scope))

    state = params.get("state", "open")
    today = timezone.localdate()
    if state == "open":
        qs = qs.filter(is_done=False)
    elif state == "done":
        qs = qs.filter(is_done=True)
    elif state == "overdue":
        qs = qs.filter(is_done=False, due_date__lt=today)
    elif state == "today":
        qs = qs.filter(is_done=False, due_date=today)
    elif state == "upcoming":
        qs = qs.filter(is_done=False, due_date__gt=today)
    return qs


@workspace_member_required
def tasks_list(request):
    ws = request.workspace
    qs = _filter_tasks(request, ws)
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "scraper/tasks.html", {
        "page": page,
        "total_matched": paginator.count,
        "team_members": workspace_members(ws),
        "filters": request.GET,
        "scope": request.GET.get("scope", "mine"),
        "state": request.GET.get("state", "open"),
    })


@workspace_member_required
@require_POST
def task_toggle(request, pk):
    task = get_object_or_404(Task, pk=pk, workspace=request.workspace)
    done = request.POST.get("done", "1") == "1"
    crm.complete_task(task, user=request.user, done=done)
    return redirect(request.POST.get("next") or "scraper:tasks")


# ---------------------------------------------------------------------------
# My Work — the rep's daily home, scoped to the active workspace
# ---------------------------------------------------------------------------
@workspace_member_required
def work(request):
    ws = request.workspace
    user = request.user
    today = timezone.localdate()

    my_open_tasks = Task.objects.filter(workspace=ws, assigned_to=user, is_done=False)
    due_today = (
        my_open_tasks.filter(due_date=today)
        .select_related("business").order_by("-created_at")
    )
    overdue = (
        my_open_tasks.filter(due_date__lt=today)
        .select_related("business").order_by("due_date")
    )

    ready_qs = (
        Business.objects.with_workspace_state(ws)
        .filter(Q(ws_status=LeadStatus.NEW) | Q(ws_status__isnull=True))
        .filter(Q(international_phone__gt="") | Q(national_phone__gt="") | ~Q(emails=[]))
        .filter(Q(ws_assigned_to_id__isnull=True) | Q(ws_assigned_to_id=user.pk))
    )

    context = {
        "my_leads_count": WorkspaceLead.objects.filter(
            workspace=ws, assigned_to=user
        ).count(),
        "due_today": list(due_today),
        "overdue": list(overdue),
        "ready": list(ready_qs[:25]),
        "ready_count": ready_qs.count(),
        "no_due_date": list(
            my_open_tasks.filter(due_date__isnull=True)
            .select_related("business").order_by("-created_at")[:25]
        ),
        "recent_my_leads": list(
            Business.objects.with_workspace_state(ws)
            .filter(ws_assigned_to_id=user.pk)
            .order_by(F("ws_last_activity_at").desc(nulls_last=True))[:10]
        ),
    }
    return render(request, "scraper/work.html", context)


# ---------------------------------------------------------------------------
# Workspaces
# ---------------------------------------------------------------------------
@login_required
def no_workspace(request):
    """Empty state for users not yet in any workspace."""
    return render(request, "scraper/no_workspace.html", {
        "is_app_admin": request.user.is_admin,
    })


@login_required
@require_POST
def workspace_switch(request):
    """Set the active workspace in the session (if the user may access it)."""
    raw = request.POST.get("workspace", "").strip()
    back = request.POST.get("next") or "scraper:dashboard"
    ws = Workspace.objects.filter(pk=raw).first() if raw.isdigit() else None
    if ws and can_access(request.user, ws):
        request.session[SESSION_KEY] = ws.pk
        messages.success(request, f"Switched to {ws.name}.")
    else:
        messages.error(request, "You can't access that workspace.")
    return redirect(back)


@login_required
def workspaces_list(request):
    workspaces = user_workspaces(request.user).order_by("-is_default", "name")
    return render(request, "scraper/workspaces.html", {
        "workspaces": workspaces,
        "can_create": request.user.is_admin,
    })


@admin_required
@require_POST
def workspace_create(request):
    name = request.POST.get("name", "").strip()
    description = request.POST.get("description", "").strip()
    if not name:
        messages.error(request, "Give the workspace a name.")
        return redirect("scraper:workspaces")
    ws = Workspace(name=name, description=description, created_by=request.user)
    ws.save()
    WorkspaceMembership.objects.get_or_create(
        workspace=ws, user=request.user, defaults={"added_by": request.user}
    )
    messages.success(request, f"Created workspace “{ws.name}”.")
    return redirect("scraper:workspace_detail", pk=ws.pk)


def _require_workspace_access(request, pk):
    """Fetch a workspace the current user may manage, or None."""
    ws = get_object_or_404(Workspace, pk=pk)
    if not can_access(request.user, ws):
        return None
    return ws


@login_required
def workspace_detail(request, pk):
    ws = _require_workspace_access(request, pk)
    if ws is None:
        messages.error(request, "You're not a member of that workspace.")
        return redirect("scraper:workspaces")
    members = ws.members.order_by("-is_active", "first_name", "email")
    member_ids = set(members.values_list("pk", flat=True))
    addable = (
        get_user_model().objects.filter(is_active=True)
        .exclude(pk__in=member_ids).order_by("first_name", "email")
    )
    return render(request, "scraper/workspace_detail.html", {
        "workspace": ws,
        "members": members,
        "addable": addable,
    })


@login_required
@require_POST
def workspace_add_member(request, pk):
    ws = _require_workspace_access(request, pk)
    if ws is None:
        messages.error(request, "You're not a member of that workspace.")
        return redirect("scraper:workspaces")
    raw = request.POST.get("user", "").strip()
    user = (
        get_user_model().objects.filter(pk=int(raw), is_active=True).first()
        if raw.isdigit() else None
    )
    if not user:
        messages.error(request, "Pick a user to add.")
        return redirect("scraper:workspace_detail", pk=ws.pk)
    _, created = WorkspaceMembership.objects.get_or_create(
        workspace=ws, user=user, defaults={"added_by": request.user}
    )
    if created:
        messages.success(request, f"Added {user.email} to {ws.name}.")
    else:
        messages.info(request, f"{user.email} is already a member.")
    return redirect("scraper:workspace_detail", pk=ws.pk)


@login_required
@require_POST
def workspace_remove_member(request, pk, user_id):
    ws = _require_workspace_access(request, pk)
    if ws is None:
        messages.error(request, "You're not a member of that workspace.")
        return redirect("scraper:workspaces")
    WorkspaceMembership.objects.filter(workspace=ws, user_id=user_id).delete()
    messages.success(request, "Member removed.")
    return redirect("scraper:workspace_detail", pk=ws.pk)


# ---------------------------------------------------------------------------
# Team management (app-level users — admin only)
# ---------------------------------------------------------------------------
@admin_required
def team_list(request):
    User = get_user_model()
    members = User.objects.order_by("-is_active", "email")
    return render(request, "scraper/team.html", {
        "members": members,
        "form": NewUserForm(),
        "roles": Role.choices,
    })


@admin_required
@require_POST
def team_create(request):
    form = NewUserForm(request.POST)
    if form.is_valid():
        user = form.save()
        messages.success(request, f"Added {user.email} as {user.get_role_display()}.")
        return redirect("scraper:team")
    # Re-render the list with form errors.
    User = get_user_model()
    members = User.objects.order_by("-is_active", "email")
    return render(request, "scraper/team.html", {
        "members": members, "form": form, "roles": Role.choices,
    })


@admin_required
@require_POST
def team_set_role(request, pk):
    User = get_user_model()
    member = get_object_or_404(User, pk=pk)
    role = request.POST.get("role", "")
    if role in {c[0] for c in Role.choices}:
        member.role = role
        member.save(update_fields=["role"])
        messages.success(request, f"{member.email} is now {member.get_role_display()}.")
    return redirect("scraper:team")


@admin_required
@require_POST
def team_toggle_active(request, pk):
    User = get_user_model()
    member = get_object_or_404(User, pk=pk)
    if member == request.user:
        messages.error(request, "You can't deactivate your own account.")
        return redirect("scraper:team")
    member.is_active = not member.is_active
    member.save(update_fields=["is_active"])
    state = "activated" if member.is_active else "deactivated"
    messages.success(request, f"{member.email} {state}.")
    return redirect("scraper:team")
