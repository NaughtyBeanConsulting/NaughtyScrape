"""Job orchestration: run search / enrichment jobs and upsert leads."""

from django.utils import timezone

from scraper.constants import EXPANSION_QUERIES
from scraper.models import (
    Business,
    CrawlJob,
    EnrichmentStatus,
    JobKind,
    JobStatus,
)
from scraper.services import enrichment, places

# Google-sourced fields we refresh on every sighting. Deliberately excludes
# the legacy ``notes`` field and enrichment fields (and per-workspace funnel
# state lives on WorkspaceLead) so re-scraping a place never clobbers manual work.
_GOOGLE_FIELDS = (
    "name", "formatted_address", "latitude", "longitude", "national_phone",
    "international_phone", "website", "google_maps_uri", "rating",
    "user_ratings_total", "price_level", "business_status", "primary_type",
    "types", "country",
)


# ---------------------------------------------------------------------------
# Country derivation
# ---------------------------------------------------------------------------
# Google's formattedAddress usually ends with a postcode (e.g. "Sydney NSW
# 2000"), not a country — so we derive the country from the clean
# search_location string ("Sydney, Australia") instead.
def _normalize_country(text):
    """Tidy casing while preserving acronyms: 'south africa' -> 'South Africa',
    'UK'/'USA'/'UAE' kept as-is."""
    text = (text or "").strip()
    if not text:
        return ""
    words = [w if w.isupper() else w.capitalize() for w in text.split()]
    return " ".join(words)[:128]


def country_from_search_location(search_location):
    """Country = last comma-separated segment of the search location."""
    loc = (search_location or "").strip()
    if not loc:
        return ""
    segment = loc.rsplit(",", 1)[-1] if "," in loc else loc
    return _normalize_country(segment)


# ---------------------------------------------------------------------------
# Enqueue helpers
# ---------------------------------------------------------------------------
def enqueue_search(query, locations, *, language="", region="", max_pages=3,
                   auto_expand=False):
    query = query.strip()
    variants = []
    if auto_expand:
        variants = list(EXPANSION_QUERIES)
        # Keep the user's own query in the mix if they typed one.
        lowered = {v.lower() for v in variants}
        if query and query.lower() not in lowered:
            variants = [query] + variants
    return CrawlJob.objects.create(
        kind=JobKind.SEARCH,
        query=query,
        locations=[loc for loc in locations if loc],
        language=language.strip(),
        region=region.strip(),
        max_pages=max(1, min(20, int(max_pages or 3))),
        auto_expand=auto_expand,
        query_variants=variants,
    )


def enqueue_enrich(business_ids=None):
    """Queue enrichment for the given business ids, or all eligible leads."""
    params = {}
    if business_ids:
        params["business_ids"] = list(business_ids)
        # Mark targets queued so the UI reflects intent immediately.
        Business.objects.filter(pk__in=business_ids, website__gt="").update(
            enrichment_status=EnrichmentStatus.PENDING
        )
    return CrawlJob.objects.create(kind=JobKind.ENRICH, params=params)


# ---------------------------------------------------------------------------
# Upsert
# ---------------------------------------------------------------------------
def upsert_business(normalized, *, job=None, search_location="", source_query=None):
    place_id = normalized.get("place_id")
    defaults = {k: normalized.get(k) for k in _GOOGLE_FIELDS}
    defaults["search_location"] = search_location
    # Prefer the country from the search location; fall back to the
    # address-derived guess only when no search location is available.
    defaults["country"] = (
        country_from_search_location(search_location)
        or normalized.get("country", "")
    )
    if source_query is None:
        source_query = (
            f"{job.query} in {search_location}".strip() if job and search_location
            else (job.query if job else "")
        )
    defaults["source_query"] = source_query
    if job:
        defaults["source_job"] = job
    obj, created = Business.objects.update_or_create(place_id=place_id, defaults=defaults)
    return obj, created


# ---------------------------------------------------------------------------
# Job runners
# ---------------------------------------------------------------------------
def _is_cancelled(job):
    return (
        CrawlJob.objects.filter(pk=job.pk).values_list("status", flat=True).first()
        == JobStatus.CANCELLED
    )


def _build_query(base_query, location):
    base_query = (base_query or "").strip()
    location = (location or "").strip()
    if base_query and location:
        return f"{base_query} in {location}"
    return base_query or location


def _build_search_tasks(job):
    """Return a list of (location, text_query) pairs for a search job.

    With auto_expand, each location fans out into one query per variant — the
    way we get past Google's ~60-results-per-query ceiling (dedupe is automatic
    on Place ID).
    """
    locations = list(job.locations) or [""]
    if job.auto_expand and job.query_variants:
        return [
            (loc, f"{variant} in {loc}" if loc else variant)
            for loc in locations
            for variant in job.query_variants
        ]
    return [(loc, _build_query(job.query, loc)) for loc in locations]


def run_search_job(job):
    tasks = _build_search_tasks(job)
    job.total = len(tasks)
    if job.auto_expand:
        job.add_log(
            f"Auto-expand: {len(job.query_variants)} queries × "
            f"{len(job.locations) or 1} location(s) = {job.total} searches.",
            save=False,
        )
    job.save(update_fields=["total", "log"])

    for location, text_query in tasks:
        if _is_cancelled(job):
            job.add_log("Cancelled — stopping.", level="warning")
            return
        if not text_query:
            job.add_log("Skipped empty query/location.", level="warning")
            job.processed += 1
            job.save(update_fields=["processed"])
            continue
        try:
            found = new = updated = 0
            for normalized, _page in places.iter_search_results(
                text_query, max_pages=job.max_pages,
                language=job.language or None, region=job.region or None,
            ):
                _obj, created = upsert_business(
                    normalized, job=job,
                    search_location=location or text_query,
                    source_query=text_query,
                )
                found += 1
                if created:
                    new += 1
                else:
                    updated += 1
            job.results_found += found
            job.new_count += new
            job.updated_count += updated
            job.add_log(
                f'"{text_query}" → {found} results ({new} new, {updated} updated).',
                save=False,
            )
        except places.PlacesAuthError as exc:
            # Auth problems won't fix themselves — fail the whole job.
            raise
        except places.PlacesError as exc:
            job.error_count += 1
            job.add_log(f'"{text_query}" failed: {exc}', level="error", save=False)
        finally:
            job.processed += 1
            job.save(update_fields=[
                "processed", "results_found", "new_count", "updated_count",
                "error_count", "log",
            ])


def run_enrich_job(job):
    ids = (job.params or {}).get("business_ids")
    qs = Business.objects.filter(website__gt="")
    if ids:
        qs = qs.filter(pk__in=ids)
    else:
        qs = qs.exclude(enrichment_status=EnrichmentStatus.DONE)
    business_ids = list(qs.values_list("pk", flat=True))

    job.total = len(business_ids)
    job.save(update_fields=["total"])
    if not business_ids:
        job.add_log("No eligible businesses (need a website).", level="warning")
        return

    for pk in business_ids:
        if _is_cancelled(job):
            job.add_log("Cancelled — stopping.", level="warning")
            return
        biz = Business.objects.filter(pk=pk).first()
        if not biz:
            continue
        try:
            data = enrichment.enrich_website(biz.website)
            biz.emails = data["emails"]
            biz.social_links = data["social_links"]
            biz.enriched_at = timezone.now()
            if data["error"]:
                biz.enrichment_status = EnrichmentStatus.FAILED
                biz.enrichment_error = data["error"]
                job.error_count += 1
            else:
                biz.enrichment_status = EnrichmentStatus.DONE
                biz.enrichment_error = ""
                if data["emails"]:
                    job.new_count += len(data["emails"])
            biz.save(update_fields=[
                "emails", "social_links", "enriched_at",
                "enrichment_status", "enrichment_error",
            ])
            if data["emails"]:
                job.add_log(f"{biz.name}: {len(data['emails'])} email(s).", save=False)
        except Exception as exc:  # never let one site kill the batch
            job.error_count += 1
            job.add_log(f"{biz.name}: {exc}", level="error", save=False)
        finally:
            job.processed += 1
            job.save(update_fields=["processed", "new_count", "error_count", "log"])


def process_job(job):
    """Run a job start to finish, updating status and timestamps."""
    job.status = JobStatus.RUNNING
    job.started_at = timezone.now()
    job.error = ""
    job.add_log(f"Started {job.get_kind_display()}.", save=False)
    job.save(update_fields=["status", "started_at", "error", "log"])

    try:
        if job.kind == JobKind.SEARCH:
            run_search_job(job)
        elif job.kind == JobKind.ENRICH:
            run_enrich_job(job)
        else:
            raise ValueError(f"Unknown job kind: {job.kind}")
    except Exception as exc:
        job.refresh_from_db(fields=["log"])
        job.status = JobStatus.FAILED
        job.error = str(exc)[:1000]
        job.finished_at = timezone.now()
        job.add_log(f"Failed: {exc}", level="error", save=False)
        job.save(update_fields=["status", "error", "finished_at", "log"])
        return job

    # Respect a cancellation that happened mid-run.
    job.refresh_from_db(fields=["status", "log"])
    if job.status != JobStatus.CANCELLED:
        job.status = JobStatus.DONE
    job.finished_at = timezone.now()
    job.add_log("Finished.", save=False)
    job.save(update_fields=["status", "finished_at", "log"])
    return job
