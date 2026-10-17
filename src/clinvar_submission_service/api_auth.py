"""Authenticates the CSS's API clients by their API keys."""

from django.http import HttpRequest
from ninja.security import APIKeyHeader

from clinvar_submission_service.models import ApiKey

API_KEY_HEADER = "X-API-Key"


class ApiKeyAuth(APIKeyHeader):
    """Accepts a request whose X-API-Key header is an active CSS API key."""

    param_name = API_KEY_HEADER

    def authenticate(self, request: HttpRequest, key: str | None) -> ApiKey | None:  # ruff: ignore[unused-method-argument] (Ninja's signature.)
        """Returns the key, which becomes request.auth, or None to reject it."""
        return ApiKey.objects.verify(key or "")
