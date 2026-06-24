"""Standalone background worker for processing crawl/enrichment jobs.

    python manage.py runworker            # run forever, polling for jobs
    python manage.py runworker --once     # drain the queue and exit

For long batch crawls, run this in its own terminal and set
RUN_INPROCESS_WORKER=False so the web process isn't also competing for jobs.
"""

from django.core.management.base import BaseCommand

from scraper import worker


class Command(BaseCommand):
    help = "Process pending crawl and enrichment jobs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--once", action="store_true",
            help="Process all currently-pending jobs, then exit.",
        )
        parser.add_argument(
            "--poll", type=float, default=2.0,
            help="Seconds to sleep when the queue is empty (default 2.0).",
        )

    def handle(self, *args, **options):
        mode = "draining queue" if options["once"] else "polling for jobs"
        self.stdout.write(self.style.SUCCESS(f"NaughtyScrape worker started ({mode})…"))
        try:
            worker.run_loop(poll_interval=options["poll"], run_once=options["once"])
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nWorker stopped."))
        if options["once"]:
            self.stdout.write(self.style.SUCCESS("Queue drained."))
