"""URL configuration for the NaughtyScrape project."""

from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from scraper.forms import EmailLoginForm

urlpatterns = [
    path("admin/", admin.site.urls),
    path(
        "accounts/login/",
        auth_views.LoginView.as_view(
            template_name="registration/login.html",
            authentication_form=EmailLoginForm,
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("scraper.urls")),
]
