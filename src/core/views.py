from django.http import HttpRequest, HttpResponse
from django.shortcuts import render

from core.tools import mounted_tools


def home(request: HttpRequest) -> HttpResponse:
    """Returns the landing page, which links to each tool."""
    return render(request, "core/home.html", {"tools": mounted_tools()})
