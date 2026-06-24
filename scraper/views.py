"""Views for the NaughtyScrape lead scraper UI (htmx + Alpine + Tailwind)."""

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
from .forms import ContactForm, NewUserForm, TagForm, TaskForm, active_member_queryset
from .models import (
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
)
from .services import crawler, crm

PAGE_SIZE = 25


def _team_members():
    return list(active_member_queryset())


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
# Lead filtering (shared by list, htmx table, and CSV export)
# ---------------------------------------------------------------------------
def filter_leads(request):
    qs = Business.objects.all()
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

    status = params.get("status", "").strip()
    if status:
        qs = qs.filter(status=status)

    enrichment = params.get("enrichment", "").strip()
    if enrichment:
        qs = qs.filter(enrichment_status=enrichment)

    country = params.get("country", "").strip()
    if country:
        qs = qs.filter(country=country)

    # --- CRM: ownership ---
    assigned = params.get("assigned", "").strip()
    if assigned == "me" and request.user.is_authenticated:
        qs = qs.filter(assigned_to=request.user)
    elif assigned == "none":
        qs = qs.filter(assigned_to__isnull=True)
    elif assigned.isdigit():
        qs = qs.filter(assigned_to_id=int(assigned))

    # --- CRM: tag ---
    tag = params.get("tag", "").strip()
    if tag:
        qs = qs.filter(tags__slug=tag)

    # --- CRM: quick work-queue views ---
    view = params.get("view", "").strip()
    if view == "mine" and request.user.is_authenticated:
        qs = qs.filter(assigned_to=request.user)
    elif view == "ready":
        # Fresh + reachable + not already someone else's job.
        qs = qs.filter(status=LeadStatus.NEW).filter(
            Q(international_phone__gt="") | Q(national_phone__gt="") | ~Q(emails=[])
        )
        if request.user.is_authenticated:
            qs = qs.filter(Q(assigned_to__isnull=True) | Q(assigned_to=request.user))

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
    qs = qs.select_related("assigned_to").prefetch_related("tags")
    # last_activity_at nulls should sort last regardless of direction.
    if sort == "-last_activity_at":
        return qs.order_by(F("last_activity_at").desc(nulls_last=True))
    if sort == "last_activity_at":
        return qs.order_by(F("last_activity_at").asc(nulls_last=True))
    return qs.order_by(sort)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    leads = Business.objects.all()
    total = leads.count()
    status_counts = {
        row["status"]: row["n"]
        for row in leads.values("status").annotate(n=Count("id"))
    }
    by_status = [
        {"value": s.value, "label": s.label, "count": status_counts.get(s.value, 0)}
        for s in LeadStatus
    ]

    # Sales funnel: cumulative "reached this stage or later" along the pipeline
    # New -> Contacted -> Qualified -> Won, derived from each lead's current
    # status. Lost / Not-a-fit are tracked separately as disqualified.
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
# Search
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
# Jobs
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
def _leads_context(request):
    qs = filter_leads(request)
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
        "team_members": _team_members(),
        "tags": Tag.objects.all(),
        "tag_colors": TAG_COLORS,
        "active_view": request.GET.get("view", ""),
    }


@login_required
def leads_list(request):
    return render(request, "scraper/leads.html", _leads_context(request))


@login_required
def leads_table(request):
    """htmx partial — the leads table body + pagination (filtered)."""
    return render(request, "scraper/partials/_leads_table.html", _leads_context(request))


@login_required
def lead_detail(request, pk):
    lead = get_object_or_404(
        Business.objects.select_related("assigned_to").prefetch_related("tags"), pk=pk
    )
    activities = lead.activities.select_related("user")[:200]
    open_tasks = lead.tasks.filter(is_done=False).select_related("assigned_to")
    done_tasks = lead.tasks.filter(is_done=True).select_related("assigned_to")[:10]
    return render(request, "scraper/lead_detail.html", {
        "lead": lead,
        "lead_statuses": LeadStatus.choices,
        "activities": activities,
        "contacts": lead.contacts.all(),
        "open_tasks": open_tasks,
        "done_tasks": done_tasks,
        "composer_types": [(t.value, t.label) for t in COMPOSER_ACTIVITY_TYPES],
        "team_members": _team_members(),
        "all_tags": Tag.objects.all(),
        "contact_form": ContactForm(),
        "task_form": TaskForm(),
    })


@login_required
@require_POST
def lead_update_status(request, pk):
    lead = get_object_or_404(Business, pk=pk)
    # The select is named status-<pk> so it stays unambiguous inside the
    # multi-row bulk form; fall back to "status" for safety.
    new_status = request.POST.get(f"status-{pk}") or request.POST.get("status", "")
    crm.change_status(lead, new_status, user=request.user)
    return render(request, "scraper/partials/_status_select.html", {
        "lead": lead, "lead_statuses": LeadStatus.choices,
    })


@login_required
@require_POST
def lead_add_activity(request, pk):
    """Log a timeline entry (note / call / email / whatsapp / meeting)."""
    lead = get_object_or_404(Business, pk=pk)
    kind = request.POST.get("kind", "note")
    valid_kinds = {t.value for t in COMPOSER_ACTIVITY_TYPES}
    if kind not in valid_kinds:
        kind = "note"
    body = request.POST.get("body", "").strip()
    if not body:
        messages.error(request, "Write something before logging it.")
        return redirect("scraper:lead_detail", pk=lead.pk)
    crm.log_activity(lead, user=request.user, kind=kind, body=body)
    messages.success(request, "Logged to the timeline.")
    return redirect("scraper:lead_detail", pk=lead.pk)


@login_required
@require_POST
def lead_assign(request, pk):
    """Set (or clear) the owner of a single lead."""
    lead = get_object_or_404(Business, pk=pk)
    raw = request.POST.get("assignee", "").strip()
    assignee = None
    if raw == "me":
        assignee = request.user
    elif raw.isdigit():
        assignee = get_user_model().objects.filter(pk=int(raw), is_active=True).first()
    crm.assign_lead(lead, assignee, by=request.user)
    messages.success(
        request,
        f"Assigned to {assignee.email}." if assignee else "Lead unassigned.",
    )
    return redirect("scraper:lead_detail", pk=lead.pk)


@login_required
@require_POST
def lead_add_tag(request, pk):
    lead = get_object_or_404(Business, pk=pk)
    tag_id = request.POST.get("tag", "").strip()
    tag = Tag.objects.filter(pk=tag_id).first() if tag_id.isdigit() else None
    if tag:
        crm.add_tag(lead, tag, user=request.user)
    return redirect("scraper:lead_detail", pk=lead.pk)


@login_required
@require_POST
def lead_remove_tag(request, pk, tag_id):
    lead = get_object_or_404(Business, pk=pk)
    tag = Tag.objects.filter(pk=tag_id).first()
    if tag:
        crm.remove_tag(lead, tag, user=request.user)
    return redirect("scraper:lead_detail", pk=lead.pk)


@login_required
@require_POST
def lead_add_contact(request, pk):
    lead = get_object_or_404(Business, pk=pk)
    form = ContactForm(request.POST)
    if form.is_valid():
        contact = form.save(commit=False)
        contact.business = lead
        contact.created_by = request.user
        # Only one primary contact per lead.
        if contact.is_primary:
            lead.contacts.update(is_primary=False)
        contact.save()
        crm.log_activity(
            lead, user=request.user, kind="contact",
            body=f"Added contact {contact.name}"
            + (f" ({contact.title})" if contact.title else ""),
            contact_id=contact.pk,
        )
        messages.success(request, f"Added contact {contact.name}.")
    else:
        messages.error(request, "Could not add contact — check the fields.")
    return redirect("scraper:lead_detail", pk=lead.pk)


@login_required
@require_POST
def lead_delete_contact(request, pk, contact_id):
    lead = get_object_or_404(Business, pk=pk)
    contact = get_object_or_404(Contact, pk=contact_id, business=lead)
    name = contact.name
    contact.delete()
    messages.info(request, f"Removed contact {name}.")
    return redirect("scraper:lead_detail", pk=lead.pk)


@login_required
@require_POST
def lead_add_task(request, pk):
    lead = get_object_or_404(Business, pk=pk)
    form = TaskForm(request.POST)
    if form.is_valid():
        data = form.cleaned_data
        crm.create_task(
            lead, title=data["title"], assignee=data.get("assigned_to"),
            by=request.user, due_date=data.get("due_date"),
        )
        messages.success(request, "Task added.")
    else:
        messages.error(request, "Give the task a title.")
    return redirect("scraper:lead_detail", pk=lead.pk)


@admin_required
@require_POST
def lead_enrich_one(request, pk):
    lead = get_object_or_404(Business, pk=pk)
    if not lead.website:
        messages.error(request, f"{lead.name} has no website to enrich.")
        return redirect("scraper:lead_detail", pk=lead.pk)
    job = crawler.enqueue_enrich([lead.pk])
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


@login_required
def leads_export(request):
    qs = filter_leads(request).prefetch_related("tags")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="naughtyscrape-leads-{timezone.now():%Y%m%d-%H%M}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow([
        "Name", "Status", "Owner", "Tags", "Rating", "Reviews", "Phone", "Website",
        "Emails", "City", "Country", "Address", "Google Maps", "Facebook",
        "Instagram", "LinkedIn", "Primary type", "Last activity",
    ])
    for b in qs.iterator():
        socials = b.social_links or {}
        writer.writerow([
            b.name, b.get_status_display(),
            b.assigned_to.email if b.assigned_to else "",
            ", ".join(t.name for t in b.tags.all()),
            b.rating or "", b.user_ratings_total,
            b.international_phone or b.national_phone, b.website,
            "; ".join(b.emails or []), b.city, b.country, b.formatted_address,
            b.google_maps_uri, socials.get("facebook", ""),
            socials.get("instagram", ""), socials.get("linkedin", ""),
            b.primary_type,
            b.last_activity_at.strftime("%Y-%m-%d %H:%M") if b.last_activity_at else "",
        ])
    return response


# ---------------------------------------------------------------------------
# Bulk actions (assign / status / tag / task), plus tag creation
# ---------------------------------------------------------------------------
@login_required
@require_POST
def leads_bulk(request):
    """Apply one action to a set of selected leads, then return to the list."""
    ids = [int(i) for i in request.POST.getlist("ids") if i.isdigit()]
    action = request.POST.get("action", "").strip()
    back = request.POST.get("next") or "scraper:leads"

    if not ids:
        messages.error(request, "Select at least one lead first.")
        return redirect(back)

    leads = list(Business.objects.filter(pk__in=ids))
    n = len(leads)

    if action == "assign":
        raw = request.POST.get("assignee", "").strip()
        assignee = None
        if raw == "me":
            assignee = request.user
        elif raw.isdigit():
            assignee = get_user_model().objects.filter(pk=int(raw), is_active=True).first()
        for lead in leads:
            crm.assign_lead(lead, assignee, by=request.user)
        who = assignee.email if assignee else "nobody"
        messages.success(request, f"Assigned {n} lead(s) to {who}.")

    elif action == "status":
        new_status = request.POST.get("status", "").strip()
        changed = sum(
            1 for lead in leads if crm.change_status(lead, new_status, user=request.user)
        )
        messages.success(request, f"Updated status on {changed} lead(s).")

    elif action == "tag":
        tag = Tag.objects.filter(pk=request.POST.get("tag", "")).first()
        if tag:
            added = sum(1 for lead in leads if crm.add_tag(lead, tag, user=request.user))
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
            get_user_model().objects.filter(pk=int(raw), is_active=True).first()
            if raw.isdigit() else None
        )
        due = _parse_due_date(request.POST.get("due_date"))
        for lead in leads:
            crm.create_task(lead, title=title, assignee=assignee, by=request.user, due_date=due)
        messages.success(request, f"Created a task on {n} lead(s).")

    else:
        messages.error(request, "Unknown bulk action.")

    return redirect(back)


@admin_required
@require_POST
def tag_create(request):
    form = TagForm(request.POST)
    if form.is_valid():
        tag = form.save()
        messages.success(request, f"Created tag “{tag.name}”.")
    else:
        first_error = next(iter(form.errors.values()))[0]
        messages.error(request, f"Could not create tag: {first_error}")
    return redirect(request.POST.get("next") or "scraper:leads")


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
def _filter_tasks(request):
    qs = Task.objects.select_related("business", "assigned_to")
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


@login_required
def tasks_list(request):
    qs = _filter_tasks(request)
    paginator = Paginator(qs, 50)
    page = paginator.get_page(request.GET.get("page"))
    return render(request, "scraper/tasks.html", {
        "page": page,
        "total_matched": paginator.count,
        "team_members": _team_members(),
        "filters": request.GET,
        "scope": request.GET.get("scope", "mine"),
        "state": request.GET.get("state", "open"),
    })


@login_required
@require_POST
def task_toggle(request, pk):
    task = get_object_or_404(Task, pk=pk)
    done = request.POST.get("done", "1") == "1"
    crm.complete_task(task, user=request.user, done=done)
    return redirect(request.POST.get("next") or "scraper:tasks")


# ---------------------------------------------------------------------------
# My Work — the rep's daily home: my leads, due today, overdue, ready to contact
# ---------------------------------------------------------------------------
@login_required
def work(request):
    user = request.user
    today = timezone.localdate()

    my_leads = Business.objects.filter(assigned_to=user)
    my_open_tasks = Task.objects.filter(assigned_to=user, is_done=False)
    due_today = (
        my_open_tasks.filter(due_date=today)
        .select_related("business").order_by("-created_at")
    )
    overdue = (
        my_open_tasks.filter(due_date__lt=today)
        .select_related("business").order_by("due_date")
    )
    ready = (
        Business.objects.filter(status=LeadStatus.NEW)
        .filter(Q(international_phone__gt="") | Q(national_phone__gt="") | ~Q(emails=[]))
        .filter(Q(assigned_to__isnull=True) | Q(assigned_to=user))
        .select_related("assigned_to")
        .prefetch_related("tags")[:25]
    )

    context = {
        "my_leads_count": my_leads.count(),
        "due_today": list(due_today),
        "overdue": list(overdue),
        "ready": list(ready),
        "ready_count": (
            Business.objects.filter(status=LeadStatus.NEW)
            .filter(Q(international_phone__gt="") | Q(national_phone__gt="") | ~Q(emails=[]))
            .filter(Q(assigned_to__isnull=True) | Q(assigned_to=user))
            .count()
        ),
        "no_due_date": list(
            my_open_tasks.filter(due_date__isnull=True)
            .select_related("business").order_by("-created_at")[:25]
        ),
        "recent_my_leads": list(
            my_leads.select_related("assigned_to").prefetch_related("tags")
            .order_by(F("last_activity_at").desc(nulls_last=True))[:10]
        ),
    }
    return render(request, "scraper/work.html", context)


# ---------------------------------------------------------------------------
# Team management (admin only)
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
