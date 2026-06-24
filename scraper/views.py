"""Views for the NaughtyScrape lead scraper UI (htmx + Alpine + Tailwind)."""

import csv

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .access import admin_required
from .constants import EXPANSION_QUERIES, QUERY_PRESETS, SEED_CITIES
from .forms import NewUserForm
from .models import (
    Business,
    CrawlJob,
    EnrichmentStatus,
    JobStatus,
    LeadStatus,
    Role,
)
from .services import crawler

PAGE_SIZE = 25


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
        )

    status = params.get("status", "").strip()
    if status:
        qs = qs.filter(status=status)

    enrichment = params.get("enrichment", "").strip()
    if enrichment:
        qs = qs.filter(enrichment_status=enrichment)

    country = params.get("country", "").strip()
    if country:
        qs = qs.filter(country=country)

    if params.get("has_email") == "1":
        qs = qs.exclude(emails=[])
    if params.get("has_website") == "1":
        qs = qs.exclude(website="")

    sort = params.get("sort", "-first_seen")
    allowed_sorts = {
        "-first_seen", "first_seen", "name", "-name",
        "-rating", "rating", "-user_ratings_total",
    }
    if sort not in allowed_sorts:
        sort = "-first_seen"
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
    lead = get_object_or_404(Business, pk=pk)
    return render(request, "scraper/lead_detail.html", {
        "lead": lead,
        "lead_statuses": LeadStatus.choices,
    })


@login_required
@require_POST
def lead_update_status(request, pk):
    lead = get_object_or_404(Business, pk=pk)
    # The select is named status-<pk> so it stays unambiguous inside the
    # multi-row bulk form; fall back to "status" for safety.
    new_status = request.POST.get(f"status-{pk}") or request.POST.get("status", "")
    valid = {c[0] for c in LeadStatus.choices}
    if new_status in valid:
        lead.status = new_status
        if new_status == LeadStatus.CONTACTED and not lead.contacted_at:
            lead.contacted_at = timezone.now()
        lead.save(update_fields=["status", "contacted_at"])
    return render(request, "scraper/partials/_status_select.html", {
        "lead": lead, "lead_statuses": LeadStatus.choices,
    })


@login_required
@require_POST
def lead_update_notes(request, pk):
    lead = get_object_or_404(Business, pk=pk)
    lead.notes = request.POST.get("notes", "")
    lead.save(update_fields=["notes"])
    if request.headers.get("HX-Request"):
        return HttpResponse('<span class="text-xs text-emerald-600">Saved ✓</span>')
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
    qs = filter_leads(request)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = (
        f'attachment; filename="naughtyscrape-leads-{timezone.now():%Y%m%d-%H%M}.csv"'
    )
    writer = csv.writer(response)
    writer.writerow([
        "Name", "Status", "Rating", "Reviews", "Phone", "Website", "Emails",
        "City", "Country", "Address", "Google Maps", "Facebook", "Instagram",
        "LinkedIn", "Primary type", "Notes",
    ])
    for b in qs.iterator():
        socials = b.social_links or {}
        writer.writerow([
            b.name, b.get_status_display(), b.rating or "", b.user_ratings_total,
            b.international_phone or b.national_phone, b.website,
            "; ".join(b.emails or []), b.city, b.country, b.formatted_address,
            b.google_maps_uri, socials.get("facebook", ""),
            socials.get("instagram", ""), socials.get("linkedin", ""),
            b.primary_type, (b.notes or "").replace("\n", " "),
        ])
    return response


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
