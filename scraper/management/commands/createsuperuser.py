"""Override Django's `createsuperuser` to use email + password only.

The custom user model (scraper.User) uses email as USERNAME_FIELD and has no
username, so we only ask for email + password. Because `scraper` is listed
before `django.contrib.auth` in INSTALLED_APPS, this command shadows the
built-in one.

    python manage.py createsuperuser                     # interactive
    python manage.py createsuperuser --email a@b.com      # prompt password only
    DJANGO_SUPERUSER_PASSWORD=secret123 \\
        python manage.py createsuperuser --email a@b.com --noinput
"""

import getpass
import os

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.core.validators import validate_email

MIN_PASSWORD_LEN = 8


class Command(BaseCommand):
    help = "Create a superuser using email + password (no username)."

    def add_arguments(self, parser):
        parser.add_argument("--email", help="Superuser email (also the login).")
        parser.add_argument(
            "--noinput", "--no-input", action="store_false", dest="interactive",
            help="Don't prompt; take --email and DJANGO_SUPERUSER_PASSWORD.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        email = (options.get("email") or "").strip().lower()

        if options["interactive"]:
            email = self._prompt_email(User, email)
            password = self._prompt_password()
        else:
            if not email:
                raise CommandError("--email is required with --noinput.")
            self._validate_email(User, email)
            password = os.environ.get("DJANGO_SUPERUSER_PASSWORD")
            if not password:
                raise CommandError(
                    "Set DJANGO_SUPERUSER_PASSWORD in the environment when using --noinput."
                )

        # create_superuser sets the Admin role for us.
        User.objects.create_superuser(email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Superuser created: {email}"))

    # -- interactive helpers ----------------------------------------------
    def _prompt_email(self, User, email):
        while True:
            if not email:
                email = input("Email: ").strip().lower()
            try:
                self._validate_email(User, email)
            except CommandError as exc:
                self.stderr.write(self.style.ERROR(str(exc)))
                email = ""
                continue
            return email

    def _prompt_password(self):
        while True:
            p1 = getpass.getpass("Password: ")
            p2 = getpass.getpass("Password (again): ")
            if p1 != p2:
                self.stderr.write(self.style.ERROR("Passwords don't match."))
                continue
            if len(p1) < MIN_PASSWORD_LEN:
                self.stderr.write(
                    self.style.ERROR(f"Password must be at least {MIN_PASSWORD_LEN} characters.")
                )
                continue
            return p1

    def _validate_email(self, User, email):
        try:
            validate_email(email)
        except ValidationError:
            raise CommandError("Enter a valid email address.")
        if User.objects.filter(email__iexact=email).exists():
            raise CommandError("A user with that email already exists.")
