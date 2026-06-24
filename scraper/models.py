"""Data models for the NaughtyScrape coffee-shop lead scraper."""

from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.db import models
from django.utils import timezone
from django.utils.text import slugify


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    VIEWER = "viewer", "Viewer"


class UserManager(BaseUserManager):
    """Manager for the email-based custom user model."""

    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", Role.ADMIN)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """Custom user: logs in by email, carries an app role. No username."""

    username = None
    email = models.EmailField("email address", unique=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.VIEWER)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email

    @property
    def is_admin(self):
        """App-level admin: a superuser or anyone with the Admin role."""
        return self.is_superuser or self.role == Role.ADMIN


class JobKind(models.TextChoices):
    SEARCH = "search", "Places search"
    ENRICH = "enrich", "Website enrichment"


class JobStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    RUNNING = "running", "Running"
    DONE = "done", "Done"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class LeadStatus(models.TextChoices):
    NEW = "new", "New"
    CONTACTED = "contacted", "Contacted"
    QUALIFIED = "qualified", "Qualified"
    WON = "won", "Won"
    LOST = "lost", "Lost"
    NOT_A_FIT = "not_a_fit", "Not a fit"


class EnrichmentStatus(models.TextChoices):
    NONE = "none", "Not attempted"
    PENDING = "pending", "Queued"
    DONE = "done", "Enriched"
    FAILED = "failed", "Failed"
    NO_WEBSITE = "no_website", "No website"


class ActivityType(models.TextChoices):
    """Kinds of timeline entry recorded against a lead."""

    NOTE = "note", "Note"
    CALL = "call", "Call"
    EMAIL = "email", "Email"
    WHATSAPP = "whatsapp", "WhatsApp"
    MEETING = "meeting", "Meeting"
    STATUS = "status", "Status change"
    ASSIGNMENT = "assignment", "Assignment"
    TAG = "tag", "Tag"
    TASK = "task", "Task"
    CONTACT = "contact", "Contact"
    SYSTEM = "system", "System"


# Manually-logged outreach touches (vs. system-generated bookkeeping entries).
# Used to decide what counts as "contact" and to power the timeline composer.
CONTACT_ACTIVITY_TYPES = (
    ActivityType.CALL, ActivityType.EMAIL, ActivityType.WHATSAPP, ActivityType.MEETING,
)
COMPOSER_ACTIVITY_TYPES = (ActivityType.NOTE,) + CONTACT_ACTIVITY_TYPES


# Statuses that mean a job is no longer claimable / still in flight.
ACTIVE_JOB_STATUSES = (JobStatus.PENDING, JobStatus.RUNNING)


class CrawlJob(models.Model):
    """A unit of background work: either a Places search or website enrichment.

    A single search job can fan out across many locations (one Google Text
    Search per location, paginated up to ``max_pages`` x 20 results).
    """

    kind = models.CharField(max_length=16, choices=JobKind.choices, default=JobKind.SEARCH)
    status = models.CharField(
        max_length=16, choices=JobStatus.choices, default=JobStatus.PENDING, db_index=True
    )

    # --- search parameters ---
    query = models.CharField(
        max_length=255, blank=True,
        help_text='Base text query, e.g. "coffee shops". Combined with each location.',
    )
    locations = models.JSONField(
        default=list, blank=True,
        help_text="List of place strings (e.g. cities). One search runs per entry.",
    )
    language = models.CharField(max_length=8, blank=True)
    region = models.CharField(max_length=8, blank=True)
    max_pages = models.PositiveSmallIntegerField(
        default=3,
        help_text="Pages of 20 results to fetch per location. Google returns at "
                  "most 3 pages (~60 results) per query, so higher values stop early.",
    )
    auto_expand = models.BooleanField(
        default=False,
        help_text="Run multiple query variants per location to get past the 60/query cap.",
    )
    query_variants = models.JSONField(
        default=list, blank=True,
        help_text="Resolved list of queries run per location when auto_expand is on.",
    )

    # --- enrichment parameters / misc ---
    params = models.JSONField(default=dict, blank=True)

    # --- progress counters ---
    total = models.PositiveIntegerField(default=0, help_text="Total units of work.")
    processed = models.PositiveIntegerField(default=0)
    results_found = models.PositiveIntegerField(default=0)
    new_count = models.PositiveIntegerField(default=0)
    updated_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)

    error = models.TextField(blank=True)
    log = models.JSONField(default=list, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        label = self.query or self.get_kind_display()
        return f"#{self.pk} {self.get_kind_display()}: {label}"

    # -- progress helpers --------------------------------------------------
    @property
    def progress_percent(self):
        if not self.total:
            return 100 if self.status == JobStatus.DONE else 0
        return min(100, round(self.processed / self.total * 100))

    @property
    def is_active(self):
        return self.status in ACTIVE_JOB_STATUSES

    @property
    def duration(self):
        if not self.started_at:
            return None
        end = self.finished_at or timezone.now()
        return end - self.started_at

    # -- logging -----------------------------------------------------------
    def add_log(self, message, level="info", save=True):
        """Append a timestamped log line, keeping only the most recent 200."""
        entry = {"ts": timezone.now().isoformat(timespec="seconds"), "level": level, "msg": message}
        log = list(self.log or [])
        log.append(entry)
        self.log = log[-200:]
        if save:
            self.save(update_fields=["log"])
        return entry

    @property
    def recent_log(self):
        return list(reversed(self.log or []))[:60]


class Business(models.Model):
    """A scraped coffee shop / business — the B2B lead."""

    # Identity (Google Place ID is stable and our dedupe key).
    place_id = models.CharField(max_length=255, unique=True)

    # --- Google Places fields ---
    name = models.CharField(max_length=512)
    formatted_address = models.CharField(max_length=1024, blank=True)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    national_phone = models.CharField(max_length=64, blank=True)
    international_phone = models.CharField(max_length=64, blank=True)
    website = models.URLField(max_length=1024, blank=True)
    google_maps_uri = models.URLField(max_length=1024, blank=True)
    rating = models.FloatField(null=True, blank=True)
    user_ratings_total = models.PositiveIntegerField(default=0)
    price_level = models.CharField(max_length=32, blank=True)
    business_status = models.CharField(max_length=32, blank=True)
    primary_type = models.CharField(max_length=128, blank=True)
    types = models.JSONField(default=list, blank=True)

    # --- derived location context ---
    city = models.CharField(max_length=128, blank=True)
    country = models.CharField(max_length=128, blank=True, db_index=True)
    search_location = models.CharField(
        max_length=255, blank=True, help_text="The location string that surfaced this lead."
    )

    # --- website enrichment ---
    emails = models.JSONField(default=list, blank=True)
    social_links = models.JSONField(default=dict, blank=True)
    enrichment_status = models.CharField(
        max_length=16, choices=EnrichmentStatus.choices, default=EnrichmentStatus.NONE, db_index=True
    )
    enrichment_error = models.TextField(blank=True)
    enriched_at = models.DateTimeField(null=True, blank=True)

    # --- lead pipeline ---
    status = models.CharField(
        max_length=16, choices=LeadStatus.choices, default=LeadStatus.NEW, db_index=True
    )
    # Legacy free-text notes. Superseded by the Activity timeline — existing
    # content was migrated into a note Activity. Kept for backwards reference.
    notes = models.TextField(blank=True)
    contacted_at = models.DateTimeField(null=True, blank=True)

    # --- CRM ownership / labels ---
    assigned_to = models.ForeignKey(
        "User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="assigned_leads", db_index=True,
    )
    tags = models.ManyToManyField("Tag", blank=True, related_name="businesses")
    last_activity_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # --- bookkeeping ---
    source_query = models.CharField(max_length=255, blank=True)
    source_job = models.ForeignKey(
        CrawlJob, null=True, blank=True, on_delete=models.SET_NULL, related_name="businesses"
    )
    first_seen = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-first_seen"]
        verbose_name_plural = "businesses"
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["enrichment_status"]),
            models.Index(fields=["country"]),
            models.Index(fields=["assigned_to", "status"]),
        ]

    def __str__(self):
        return self.name

    @property
    def has_website(self):
        return bool(self.website)

    @property
    def has_email(self):
        return bool(self.emails)

    @property
    def primary_email(self):
        return self.emails[0] if self.emails else ""

    @property
    def has_phone(self):
        return bool(self.international_phone or self.national_phone)

    @property
    def best_phone(self):
        return self.international_phone or self.national_phone

    @property
    def is_contactable(self):
        """Has at least one way to reach out."""
        return self.has_email or self.has_phone

    @property
    def is_ready_to_contact(self):
        """A fresh, reachable lead that no one has worked yet."""
        return self.status == LeadStatus.NEW and self.is_contactable


# Tailwind colour names that have ready-made badge classes safelisted for tags.
TAG_COLORS = [
    "stone", "amber", "sky", "emerald", "violet", "rose", "blue", "teal",
]


class Tag(models.Model):
    """A free-form label that can be applied to many leads."""

    name = models.CharField(max_length=64, unique=True)
    slug = models.SlugField(max_length=80, unique=True, blank=True)
    color = models.CharField(max_length=16, default="stone")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:80] or "tag"
            slug, n = base, 2
            while Tag.objects.exclude(pk=self.pk).filter(slug=slug).exists():
                slug = f"{base[:76]}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Contact(models.Model):
    """A named person at a lead business — who you actually talk to."""

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="contacts"
    )
    name = models.CharField(max_length=255)
    title = models.CharField(max_length=128, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=64, blank=True)
    is_primary = models.BooleanField(default=False)
    note = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        "User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-is_primary", "name"]

    def __str__(self):
        return self.name


class Activity(models.Model):
    """A single timeline entry against a lead (note, call, status change…)."""

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="activities"
    )
    user = models.ForeignKey(
        "User", null=True, blank=True, on_delete=models.SET_NULL, related_name="activities"
    )
    kind = models.CharField(
        max_length=16, choices=ActivityType.choices,
        default=ActivityType.NOTE, db_index=True,
    )
    body = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "activities"

    def __str__(self):
        return f"{self.get_kind_display()} on {self.business_id}"

    @property
    def is_touch(self):
        """True for manually-logged outreach (counts as contacting the lead)."""
        return self.kind in CONTACT_ACTIVITY_TYPES


class Task(models.Model):
    """A follow-up / to-do attached to a lead, with an optional due date."""

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="tasks"
    )
    title = models.CharField(max_length=255)
    assigned_to = models.ForeignKey(
        "User", null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks"
    )
    created_by = models.ForeignKey(
        "User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    due_date = models.DateField(null=True, blank=True, db_index=True)
    is_done = models.BooleanField(default=False, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["is_done", models.F("due_date").asc(nulls_last=True), "-created_at"]

    def __str__(self):
        return self.title

    @property
    def is_overdue(self):
        return bool(
            not self.is_done and self.due_date and self.due_date < timezone.localdate()
        )

    @property
    def is_due_today(self):
        return bool(not self.is_done and self.due_date == timezone.localdate())


class LeadAssignment(models.Model):
    """Audit log of who a lead was handed to, and by whom.

    ``Business.assigned_to`` holds the *current* owner for fast filtering;
    this model keeps the full history of hand-offs.
    """

    business = models.ForeignKey(
        Business, on_delete=models.CASCADE, related_name="assignments"
    )
    user = models.ForeignKey(
        "User", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="lead_assignments",
    )
    assigned_by = models.ForeignKey(
        "User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.business_id} → {self.user_id or 'unassigned'}"
