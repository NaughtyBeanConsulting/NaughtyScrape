"""Re-derive Business.country from search_location (fixing postcode junk).

Google's formattedAddress often ends with a postcode rather than a country, so
old rows have values like "Sydney NSW 2000" in `country`. This recomputes
country from the clean `search_location` ("Sydney, Australia" -> "Australia").

    python manage.py fix_countries            # apply
    python manage.py fix_countries --dry-run  # preview only
"""

from django.core.management.base import BaseCommand

from scraper.models import Business
from scraper.services.crawler import country_from_search_location
from scraper.services.places import _country_from_address


class Command(BaseCommand):
    help = "Re-derive Business.country from search_location."

    def add_arguments(self, parser):
        parser.add_argument("--dry-run", action="store_true", help="Preview changes only.")

    def handle(self, *args, **options):
        dry = options["dry_run"]
        updated = 0

        # Fast path: bulk update per distinct search_location (a handful of values).
        # .order_by("search_location") clears the model's default -first_seen
        # ordering, which would otherwise break .distinct() (Django appends the
        # ordering column to the SELECT, making every row distinct).
        locations = (
            Business.objects.exclude(search_location="")
            .order_by("search_location")
            .values_list("search_location", flat=True)
            .distinct()
        )
        for loc in locations:
            country = country_from_search_location(loc)
            qs = Business.objects.filter(search_location=loc).exclude(country=country)
            n = qs.count()
            if n:
                self.stdout.write(f"  {loc!r:45} -> {country!r:18} ({n} rows)")
                if not dry:
                    qs.update(country=country)
                updated += n

        # Fallback: rows with no search_location -> derive from the address.
        for b in Business.objects.filter(search_location=""):
            country = _country_from_address(b.formatted_address)
            if country and country != b.country:
                if not dry:
                    b.country = country
                    b.save(update_fields=["country"])
                updated += 1

        verb = "Would update" if dry else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} {updated} row(s)."))
