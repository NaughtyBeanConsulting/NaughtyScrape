"""Best-effort website enrichment: pull emails and social links from a site.

Google never returns email addresses, so for outreach we visit the business
website (homepage + a likely "contact" page) and extract any emails and social
profile links we can find. This is heuristic and intentionally forgiving.
"""

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from django.conf import settings

EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# Local-part / domain fragments that signal a junk or placeholder address.
EMAIL_BLOCKLIST = (
    "example.com", "example.org", "sentry.io", "wix.com", "wixpress.com",
    "godaddy.com", "domain.com", "email.com", "yourdomain", "sentry-next",
)
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp")

SOCIAL_DOMAINS = {
    "facebook.com": "facebook",
    "instagram.com": "instagram",
    "linkedin.com": "linkedin",
    "twitter.com": "twitter",
    "x.com": "twitter",
    "youtube.com": "youtube",
    "tiktok.com": "tiktok",
}

# Anchor text / href hints for a contact page worth a second fetch.
CONTACT_HINTS = ("contact", "kontakt", "about", "reach", "get-in-touch", "impressum")


def _normalize_url(url):
    url = (url or "").strip()
    if not url:
        return ""
    if not urlparse(url).scheme:
        url = "https://" + url
    return url


def _is_real_email(email):
    low = email.lower()
    if low.endswith(IMAGE_SUFFIXES):
        return False
    return not any(bad in low for bad in EMAIL_BLOCKLIST)


def _fetch(url, timeout):
    headers = {"User-Agent": settings.SCRAPE_USER_AGENT, "Accept": "text/html,*/*"}
    resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
    resp.raise_for_status()
    ctype = resp.headers.get("Content-Type", "")
    if "html" not in ctype and "text" not in ctype:
        return None
    return resp.text


def _extract(html, base_url):
    """Return (emails set, socials dict, contact_url or None) from one page."""
    soup = BeautifulSoup(html, "html.parser")
    emails = set()
    socials = {}
    contact_url = None

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        low = href.lower()
        if low.startswith("mailto:"):
            addr = low[len("mailto:"):].split("?")[0].strip()
            if addr and _is_real_email(addr):
                emails.add(addr)
            continue
        for domain, name in SOCIAL_DOMAINS.items():
            if domain in low and name not in socials:
                socials[name] = urljoin(base_url, href)
        if contact_url is None and any(h in low for h in CONTACT_HINTS):
            candidate = urljoin(base_url, href)
            # Only follow links on the same registered host.
            if urlparse(candidate).netloc == urlparse(base_url).netloc:
                contact_url = candidate

    for match in EMAIL_RE.findall(html):
        if _is_real_email(match):
            emails.add(match.lower())

    return emails, socials, contact_url


def enrich_website(url):
    """Fetch a website (and one contact page) and extract emails + socials.

    Returns a dict: {"emails": [...], "social_links": {...}, "error": str|""}.
    Never raises — failures are reported via the "error" key.
    """
    result = {"emails": [], "social_links": {}, "error": ""}
    start = _normalize_url(url)
    if not start:
        result["error"] = "No website URL."
        return result

    timeout = settings.SCRAPE_HTTP_TIMEOUT
    emails, socials = set(), {}
    try:
        html = _fetch(start, timeout)
        if html:
            e, s, contact = _extract(html, start)
            emails |= e
            socials.update(s)
            # One extra fetch of a contact/about page if we found one.
            if contact and contact != start:
                try:
                    chtml = _fetch(contact, timeout)
                    if chtml:
                        e2, s2, _ = _extract(chtml, contact)
                        emails |= e2
                        for k, v in s2.items():
                            socials.setdefault(k, v)
                except requests.RequestException:
                    pass
    except requests.RequestException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return result

    result["emails"] = sorted(emails)
    result["social_links"] = socials
    return result
