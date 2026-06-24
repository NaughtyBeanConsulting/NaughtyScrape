"""
Base Django settings for the NaughtyScrape project.

Environment variables are loaded from a local `.env` file via python-dotenv.
This is an internal lead-generation tool and is not intended for production,
so several "production hardening" knobs are intentionally relaxed.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Project root (the directory that holds manage.py). settings/base.py lives at
# <root>/app/settings/base.py, so we walk up three parents.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Load .env from the project root before reading any os.environ values.
load_dotenv(BASE_DIR / ".env")


def env(key, default=None):
    return os.environ.get(key, default)


def env_bool(key, default=False):
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


def env_list(key, default=None):
    val = os.environ.get(key)
    if not val:
        return list(default or [])
    return [item.strip() for item in val.split(",") if item.strip()]


# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------
SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-please-change")
DEBUG = env_bool("DEBUG", True)
ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", ["localhost", "127.0.0.1"])
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
SITE_URL = env("SITE_URL", "http://localhost:8000")

TURNSTILE_SITE_KEY = env("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = env("TURNSTILE_SECRET_KEY", "")
TURNSTILE_VERIFY_URL = env(
    "TURNSTILE_VERIFY_URL",
    "https://challenges.cloudflare.com/turnstile/v0/siteverify",
)
TURNSTILE_TIMEOUT = float(env("TURNSTILE_TIMEOUT", "5"))
TURNSTILE_ENABLED = env_bool(
    "TURNSTILE_ENABLED",
    bool(TURNSTILE_SITE_KEY and TURNSTILE_SECRET_KEY),
)

INSTALLED_APPS = [
    # Listed first so its `createsuperuser` overrides django.contrib.auth's
    # (Django resolves command name clashes in favour of the earliest app).
    "scraper",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "app.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "scraper.context.nav_counts",
            ],
        },
    },
]

WSGI_APPLICATION = "app.wsgi.application"
ASGI_APPLICATION = "app.asgi.application"

# ---------------------------------------------------------------------------
# Database (Postgres via psycopg 3)
# ---------------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("DB_NAME", "naughtyscrape"),
        "USER": env("DB_USER", "postgres"),
        "PASSWORD": env("DB_PASSWORD", ""),
        "HOST": env("DB_HOST", "127.0.0.1"),
        "PORT": env("DB_PORT", "5432"),
    }
}

AUTH_PASSWORD_VALIDATORS = []

# Authentication (email-based login; usernames are stored as the email).
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "scraper:dashboard"
LOGOUT_REDIRECT_URL = "login"

# ---------------------------------------------------------------------------
# I18N
# ---------------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Custom user model: email is the login, no username.
AUTH_USER_MODEL = "scraper.User"

MESSAGE_STORAGE = "django.contrib.messages.storage.session.SessionStorage"

# ---------------------------------------------------------------------------
# Scraper / Google Places configuration
# ---------------------------------------------------------------------------
# Google Places API (New) key. Add GOOGLE_MAPS_API_KEY=... to your .env.
GOOGLE_MAPS_API_KEY = env("GOOGLE_MAPS_API_KEY", "")

# Default language/region applied to searches when not specified per-job.
PLACES_DEFAULT_LANGUAGE = env("PLACES_DEFAULT_LANGUAGE", "en")
PLACES_DEFAULT_REGION = env("PLACES_DEFAULT_REGION", "")

# Polite delay (seconds) between outbound Google / website requests.
SCRAPE_REQUEST_DELAY = float(env("SCRAPE_REQUEST_DELAY", "2.0"))

# HTTP timeout (seconds) for outbound requests.
SCRAPE_HTTP_TIMEOUT = float(env("SCRAPE_HTTP_TIMEOUT", "15"))

# User-Agent used when fetching business websites for email enrichment.
SCRAPE_USER_AGENT = env(
    "SCRAPE_USER_AGENT",
    "Mozilla/5.0 (compatible; NaughtyScrapeBot/1.0; +https://clickcollect.coffee)",
)

# When True (default in DEBUG), a background worker thread starts inside the
# web process so `runserver` alone can process jobs. Set to False and run
# `python manage.py runworker` in a separate terminal for heavy batch crawls.
RUN_INPROCESS_WORKER = env_bool("RUN_INPROCESS_WORKER", DEBUG)

# ---------------------------------------------------------------------------
# Sentry (error monitoring) — only initialised when SENTRY_DSN is set.
# The Django integration is auto-enabled by sentry-sdk.
# ---------------------------------------------------------------------------
SENTRY_DSN = env("SENTRY_DSN", "")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        # Send request headers and IP for users. See:
        # https://docs.sentry.io/platforms/python/data-management/data-collected/
        send_default_pii=True,
        environment="development" if DEBUG else "production",
    )
