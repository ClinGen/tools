"""Houses the AS's pages."""

from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render

from affiliations_service.history import describe_history
from affiliations_service.models import CDWG, Affiliation, Membership
from auth_.permissions import tool_permission_required
from core.tools import get_tool


@tool_permission_required("has_as_permissions")
def index(request: HttpRequest) -> HttpResponse:
    """Lists affiliations, with a search box and filters.

    `q` searches names and IDs; `type`, `status`, and `cdwg` filter the list. Deleted
    affiliations are left out.

    Returns:
        The affiliation list.
    """
    affiliations = Affiliation.objects.active().select_related("cdwg")
    query = request.GET.get("q", "").strip()
    if query:
        matches = Q(full_name__icontains=query) | Q(short_name__icontains=query)
        if query.isdigit():
            matches |= Q(affiliation_id=query) | Q(expert_panel_id=query)
        affiliations = affiliations.filter(matches)
    filters = {
        "type": request.GET.get("type", ""),
        "status": request.GET.get("status", ""),
        "cdwg": request.GET.get("cdwg", ""),
    }
    if filters["type"]:
        affiliations = affiliations.filter(type=filters["type"])
    if filters["status"]:
        affiliations = affiliations.filter(status=filters["status"])
    if filters["cdwg"]:
        affiliations = affiliations.filter(cdwg__pk=filters["cdwg"])
    return render(
        request,
        "affiliations_service/index.html",
        {
            "tool": get_tool("as"),
            "affiliations": affiliations,
            "query": query,
            "filters": filters,
            "types": Affiliation.Type.choices,
            "statuses": Affiliation.Status.choices,
            "cdwgs": CDWG.objects.all(),
        },
    )


@tool_permission_required("has_as_permissions")
def affiliation_detail(request: HttpRequest, pk: str) -> HttpResponse:
    """Shows an affiliation, its members, and its history.

    Returns:
        The affiliation's page.
    """
    affiliation = get_object_or_404(
        Affiliation.objects.select_related("cdwg").prefetch_related(
            "clinvar_submitter_ids"
        ),
        pk=pk,
    )
    memberships = affiliation.memberships.select_related("person")
    current = memberships.current()
    members_by_role = [
        (label, [m for m in current if m.role == role])
        for role, label in Membership.Role.choices
    ]
    return render(
        request,
        "affiliations_service/affiliation_detail.html",
        {
            "tool": get_tool("as"),
            "affiliation": affiliation,
            "members_by_role": members_by_role,
            "past_memberships": memberships.exclude(pk__in=current).order_by(
                "-end_date"
            ),
            "history": describe_history(affiliation, "the affiliation"),
        },
    )
