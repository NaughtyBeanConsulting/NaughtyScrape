"""Create (or update) an admin user that logs in by email.

    python manage.py bootstrap_admin --email you@example.com --password secret123
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from scraper.models import Role


class Command(BaseCommand):
    help = "Create or update an admin user (email login)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--password", required=True)

    def handle(self, *args, **options):
        User = get_user_model()
        email = options["email"].strip().lower()
        password = options["password"]
        if len(password) < 8:
            raise CommandError("Password must be at least 8 characters.")

        user, created = User.objects.get_or_create(email=email)
        user.is_staff = True
        user.is_superuser = True
        user.role = Role.ADMIN
        user.set_password(password)
        user.save()

        verb = "Created" if created else "Updated"
        self.stdout.write(self.style.SUCCESS(f"{verb} admin {email}."))
