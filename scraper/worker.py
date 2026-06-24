"""Background job worker.

Two ways to run jobs:

1. In-process thread (default in DEBUG): a daemon thread started from
   ``ScraperConfig.ready`` so ``manage.py runserver`` alone drains the queue.
2. ``manage.py runworker``: a standalone worker for heavy batch crawls
   (run with ``--noreload`` so it isn't restarted mid-job).

Both use the same claim/process logic. Claiming uses ``SELECT ... FOR UPDATE
SKIP LOCKED`` so multiple workers never grab the same job.
"""

import threading
import time

from django.db import close_old_connections, transaction

from scraper.models import CrawlJob, JobStatus
from scraper.services.crawler import process_job

_started = False
_start_lock = threading.Lock()


def requeue_stale_jobs():
    """Reset jobs left RUNNING by an interrupted worker back to PENDING."""
    return CrawlJob.objects.filter(status=JobStatus.RUNNING).update(
        status=JobStatus.PENDING
    )


def claim_next_job():
    """Atomically claim the oldest pending job, or return None."""
    with transaction.atomic():
        job = (
            CrawlJob.objects.select_for_update(skip_locked=True)
            .filter(status=JobStatus.PENDING)
            .order_by("created_at")
            .first()
        )
        if job is None:
            return None
        job.status = JobStatus.RUNNING
        job.save(update_fields=["status"])
        return job


def run_loop(poll_interval=2.0, stop_event=None, run_once=False):
    """Process jobs until stopped (or, if run_once, until the queue drains)."""
    requeue_stale_jobs()
    while not (stop_event and stop_event.is_set()):
        close_old_connections()
        job = claim_next_job()
        if job is None:
            if run_once:
                return
            time.sleep(poll_interval)
            continue
        try:
            process_job(job)
        finally:
            close_old_connections()


def start_inprocess_worker(poll_interval=2.0):
    """Start (once) a daemon worker thread inside the current process."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True
    thread = threading.Thread(
        target=run_loop,
        kwargs={"poll_interval": poll_interval},
        name="naughtyscrape-worker",
        daemon=True,
    )
    thread.start()
    print("☕ NaughtyScrape in-process job worker started.")
