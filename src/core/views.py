from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from core.tools import visible_tools


def home(request: HttpRequest) -> HttpResponse:
    """Returns the landing page, which links to each tool the user may see."""
    return render(request, "core/home.html", {"tools": visible_tools(request)})
