"""Development settings. Selected via DJANGO_SETTINGS_MODULE=app.settings.development."""

from .base import *  # noqa: F401,F403
from .base import DEBUG  # explicit import for linters

# Keep everything from base; this module exists so the env's
# DJANGO_SETTINGS_MODULE=app.settings.development resolves cleanly and so
# environment-specific overrides have an obvious home.

INTERNAL_IPS = ["127.0.0.1"]
