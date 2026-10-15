"""Configures URLs for the project."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("", include("core.urls")),
    path("admin/", admin.site.urls),
    path("auth/", include("auth_.urls")),
    path("ets/", include("email_transfer_service.urls")),
]
