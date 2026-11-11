"""Authenticates the AS's API clients by their API keys."""

from django.http import HttpRequest
from ninja.security import APIKeyHeader

from affiliations_service.models import ApiKey

API_KEY_HEADER = "X-Api-Key"


class ApiKeyAuth(APIKeyHeader):
    """Accepts a request whose X-Api-Key header is an active AS API key."""

    param_name = API_KEY_HEADER

    def authenticate(self, request: HttpRequest, key: str | None) -> ApiKey | None:  # ruff: ignore[unused-method-argument] (Ninja's signature.)
        """Returns the key, which becomes request.auth, or None to reject it."""
        return ApiKey.objects.verify(key or "")
