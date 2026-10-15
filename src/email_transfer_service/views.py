from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from auth_.permissions import tool_permission_required


@tool_permission_required("has_ets_permissions")
def index(request: HttpRequest) -> HttpResponse:
    """Returns the ETS's home page."""
    return render(request, "email_transfer_service/index.html")
