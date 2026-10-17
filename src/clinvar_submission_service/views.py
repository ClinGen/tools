from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from auth_.permissions import tool_permission_required
from core.tools import get_tool


@tool_permission_required("has_css_permissions")
def index(request: HttpRequest) -> HttpResponse:
    """Shows the CSS's home page.

    Returns:
        The home page.
    """
    return render(
        request,
        "clinvar_submission_service/index.html",
        {"tool": get_tool("css")},
    )
