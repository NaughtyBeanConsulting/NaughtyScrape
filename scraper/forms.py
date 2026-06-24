"""Forms: email-based login and team user creation."""

import logging

import requests
from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm

from .models import Role

User = get_user_model()
logger = logging.getLogger(__name__)

_INPUT = "w-full rounded-md border border-gray-300 px-3 py-2 focus:border-amber-400 focus:ring-amber-400"


class EmailLoginForm(AuthenticationForm):
    """Login by email. Usernames are stored as the (lowercased) email."""

    username = forms.EmailField(
        label="Email",
        widget=forms.EmailInput(attrs={"autofocus": True, "class": _INPUT, "placeholder": "you@example.com"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.turnstile_enabled = settings.TURNSTILE_ENABLED
        self.turnstile_site_key = settings.TURNSTILE_SITE_KEY
        self.fields["password"].widget.attrs.update({"class": _INPUT})

    def clean_username(self):
        return self.cleaned_data["username"].strip().lower()

    def clean(self):
        if self.turnstile_enabled:
            self._validate_turnstile()
        return super().clean()

    def _validate_turnstile(self):
        if not settings.TURNSTILE_SITE_KEY or not settings.TURNSTILE_SECRET_KEY:
            raise forms.ValidationError("Sign-in protection is not configured.")

        token = self.data.get("cf-turnstile-response", "").strip()
        if not token:
            raise forms.ValidationError("Please complete the security check.")

        remote_ip = None
        if self.request:
            remote_ip = self.request.META.get("REMOTE_ADDR")

        data = {
            "secret": settings.TURNSTILE_SECRET_KEY,
            "response": token,
        }
        if remote_ip:
            data["remoteip"] = remote_ip

        try:
            response = requests.post(
                settings.TURNSTILE_VERIFY_URL,
                data=data,
                timeout=settings.TURNSTILE_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError):
            logger.exception("Cloudflare Turnstile verification failed")
            raise forms.ValidationError(
                "We could not verify the security check. Please try again."
            )

        if not payload.get("success"):
            logger.warning(
                "Cloudflare Turnstile rejected login attempt: %s",
                payload.get("error-codes", []),
            )
            raise forms.ValidationError("Security check failed. Please try again.")


class NewUserForm(forms.Form):
    """Admin-only form to add a team member."""

    email = forms.EmailField(widget=forms.EmailInput(attrs={"class": _INPUT}))
    full_name = forms.CharField(
        required=False, widget=forms.TextInput(attrs={"class": _INPUT})
    )
    role = forms.ChoiceField(
        choices=Role.choices, widget=forms.Select(attrs={"class": _INPUT})
    )
    password = forms.CharField(
        min_length=8,
        widget=forms.PasswordInput(attrs={"class": _INPUT, "placeholder": "min 8 characters"}),
    )

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("A user with that email already exists.")
        return email

    def save(self):
        data = self.cleaned_data
        first, _, last = data["full_name"].strip().partition(" ")
        return User.objects.create_user(
            email=data["email"],
            password=data["password"],
            first_name=first,
            last_name=last,
            role=data["role"],
        )
