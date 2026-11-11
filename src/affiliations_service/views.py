"""Houses the AS's pages."""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from auth_.permissions import tool_permission_required
from core.tools import get_tool


@tool_permission_required("has_as_permissions")
def index(request: HttpRequest) -> HttpResponse:
    """Shows the AS's home page.

    Returns:
        The home page.
    """
    return render(
        request,
        "affiliations_service/index.html",
        {"tool": get_tool("as")},
    )
