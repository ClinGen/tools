"""Houses middleware used throughout the app."""

from collections.abc import Callable
from typing import Any

import sentry_sdk
from django.http import HttpRequest, HttpResponse

from core.tools import TOOLS

TOOL_NAMESPACES = {tool.namespace for tool in TOOLS}


class ToolTagMiddleware:
    """Tags each Sentry event with the tool that handled the request.

    The tag is the tool's URL namespace (as, css, or ets). Requests outside a tool, such
    as the landing page or sign-in, get no tag.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        """Stores the next handler in Django's middleware chain."""
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        return self.get_response(request)

    def process_view(
        self,
        request: HttpRequest,
        view_func: Callable,  # ruff: ignore[unused-method-argument] (Django's signature.)
        view_args: tuple[Any, ...],  # ruff: ignore[unused-method-argument]
        view_kwargs: dict[str, Any],  # ruff: ignore[unused-method-argument]
    ) -> None:
        """Sets the tool tag once the URL has been resolved."""
        match = request.resolver_match
        namespace = match.namespaces[0] if match and match.namespaces else None
        if namespace in TOOL_NAMESPACES:
            sentry_sdk.set_tag("tool", namespace)
