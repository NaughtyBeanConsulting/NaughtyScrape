"""Client for the Google Places API (New) Text Search endpoint.

Docs: https://developers.google.com/maps/documentation/places/web-service/text-search

A single ``searchText`` call returns up to 20 places plus a ``nextPageToken``.
Google caps a query at ~60 results (3 pages). To cover "coffee shops around the
world" you fan out across many location strings — see ``crawler.run_search_job``.
"""

import time

import requests
from django.conf import settings

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"

# Field mask controls which fields come back (and the billing SKU tier).
# We request contact details (phone + website) because they are the point of
# B2B lead gen — this lands in the "Enterprise + Atmosphere" SKU tier.
DEFAULT_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.location",
    "places.rating",
    "places.userRatingCount",
    "places.priceLevel",
    "places.businessStatus",
    "places.primaryType",
    "places.types",
    "places.nationalPhoneNumber",
    "places.internationalPhoneNumber",
    "places.websiteUri",
    "places.googleMapsUri",
    "nextPageToken",
])


class PlacesError(Exception):
    """Base error for Places API problems."""


class PlacesAuthError(PlacesError):
    """API key missing, invalid, or not authorized for Places API (New)."""


class PlacesQuotaError(PlacesError):
    """Rate limit / quota exceeded (HTTP 429)."""


def _api_key(api_key=None):
    key = api_key or settings.GOOGLE_MAPS_API_KEY
    if not key:
        raise PlacesAuthError(
            "GOOGLE_MAPS_API_KEY is not set. Add it to your .env file."
        )
    return key


def search_text(text_query, *, language=None, region=None, page_token=None,
                page_size=20, api_key=None, field_mask=DEFAULT_FIELD_MASK,
                timeout=None):
    """Make a single Places API (New) Text Search request, returning raw JSON."""
    key = _api_key(api_key)
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": field_mask,
    }
    body = {"textQuery": text_query, "pageSize": page_size}
    if language:
        body["languageCode"] = language
    if region:
        body["regionCode"] = region
    if page_token:
        # When paginating, Google requires the original query in the body too.
        body["pageToken"] = page_token

    try:
        resp = requests.post(
            SEARCH_URL, json=body, headers=headers,
            timeout=timeout or settings.SCRAPE_HTTP_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise PlacesError(f"Request failed: {exc}") from exc

    if resp.status_code == 429:
        raise PlacesQuotaError("Google rate limit hit (HTTP 429).")
    if resp.status_code in (401, 403):
        raise PlacesAuthError(_error_message(resp) or "Not authorized (check key / API enabled).")
    if resp.status_code >= 400:
        raise PlacesError(_error_message(resp) or f"HTTP {resp.status_code}")

    return resp.json()


def _error_message(resp):
    try:
        return resp.json().get("error", {}).get("message")
    except ValueError:
        return resp.text[:300]


def normalize_place(p):
    """Convert a raw Places API place object into our Business field dict."""
    address = p.get("formattedAddress", "") or ""
    return {
        "place_id": p.get("id", ""),
        "name": (p.get("displayName") or {}).get("text", "") or "",
        "formatted_address": address,
        "latitude": (p.get("location") or {}).get("latitude"),
        "longitude": (p.get("location") or {}).get("longitude"),
        "national_phone": p.get("nationalPhoneNumber", "") or "",
        "international_phone": p.get("internationalPhoneNumber", "") or "",
        "website": p.get("websiteUri", "") or "",
        "google_maps_uri": p.get("googleMapsUri", "") or "",
        "rating": p.get("rating"),
        "user_ratings_total": p.get("userRatingCount", 0) or 0,
        "price_level": p.get("priceLevel", "") or "",
        "business_status": p.get("businessStatus", "") or "",
        "primary_type": p.get("primaryType", "") or "",
        "types": p.get("types", []) or [],
        "country": _country_from_address(address),
    }


def _country_from_address(address):
    """Best-effort country extraction: the last comma-separated segment."""
    if not address:
        return ""
    return address.split(",")[-1].strip()[:128]


def iter_search_results(text_query, *, max_pages=3, language=None, region=None,
                        delay=None, api_key=None):
    """Yield normalized places for a query, following pagination up to max_pages.

    Yields tuples of (normalized_place_dict, page_number).
    """
    delay = settings.SCRAPE_REQUEST_DELAY if delay is None else delay
    page_token = None
    for page in range(1, max(1, max_pages) + 1):
        if page > 1 and delay:
            # nextPageToken can need a moment to become valid; also be polite.
            time.sleep(delay)
        data = search_text(
            text_query, language=language, region=region,
            page_token=page_token, api_key=api_key,
        )
        for place in data.get("places", []):
            normalized = normalize_place(place)
            if normalized["place_id"]:
                yield normalized, page
        page_token = data.get("nextPageToken")
        if not page_token:
            break
