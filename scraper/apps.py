import os
import sys

from django.apps import AppConfig
from django.conf import settings


class ScraperConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "scraper"

    def ready(self):
        if not settings.RUN_INPROCESS_WORKER:
            return
        # Only the dev server should host the in-process worker — not migrate,
        # shell, tests, or the runworker command itself.
        if "runserver" not in sys.argv:
            return
        # With the autoreloader, only the reloaded child (RUN_MAIN=true) should
        # start the thread; the parent watcher process should not.
        if os.environ.get("RUN_MAIN") != "true" and "--noreload" not in sys.argv:
            return
        from scraper.worker import start_inprocess_worker

        start_inprocess_worker()
