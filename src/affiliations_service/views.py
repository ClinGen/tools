"""Houses the AS's pages."""

from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from affiliations_service.forms import (
    AffiliationCreateForm,
    AffiliationEditForm,
    SubmitterIdFormSet,
)
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


def _affiliation_form(
    request: HttpRequest,
    form_class: type[AffiliationCreateForm | AffiliationEditForm],
    affiliation: Affiliation | None,
) -> HttpResponse:
    """Shows an affiliation form, and saves the affiliation when the form is valid.

    Args:
        request: The current request.
        form_class: The create or edit form.
        affiliation: The affiliation to edit, or None to create one.

    Returns:
        The form page, or a redirect to the affiliation's page once it's saved.
    """
    data = request.POST if request.method == "POST" else None
    form = form_class(data, instance=affiliation)
    formset = SubmitterIdFormSet(data, instance=affiliation)
    if data is not None and form.is_valid():
        # The formset needs the saved affiliation, so check it once the form is valid.
        with transaction.atomic():
            saved = form.save()
            formset.instance = saved
            if formset.is_valid():
                formset.save()
                return redirect(saved)
            transaction.set_rollback(True)
        if affiliation is None:
            form.instance.pk = None
            form.instance._state.adding = True  # ruff: ignore[private-member-access]
    return render(
        request,
        "affiliations_service/affiliation_form.html",
        {
            "tool": get_tool("as"),
            "form": form,
            "formset": formset,
            "affiliation": affiliation,
        },
    )


@tool_permission_required("has_as_permissions")
def affiliation_create(request: HttpRequest) -> HttpResponse:
    """Creates an affiliation. Its IDs are assigned when it's saved.

    Returns:
        The form, or a redirect to the new affiliation's page.
    """
    return _affiliation_form(request, AffiliationCreateForm, None)


@tool_permission_required("has_as_permissions")
def affiliation_edit(request: HttpRequest, pk: str) -> HttpResponse:
    """Changes an affiliation, apart from its IDs, type, and GPM UUID.

    Returns:
        The form, or a redirect to the affiliation's page.
    """
    affiliation = get_object_or_404(Affiliation, pk=pk)
    return _affiliation_form(request, AffiliationEditForm, affiliation)


@tool_permission_required("has_as_permissions")
def affiliation_delete(request: HttpRequest, pk: str) -> HttpResponse:
    """Asks staff to confirm, then marks an affiliation deleted.

    Returns:
        The confirmation page, or a redirect to the affiliation list.
    """
    affiliation = get_object_or_404(Affiliation, pk=pk)
    if request.method == "POST":
        affiliation.delete()
        return redirect("as:index")
    return render(
        request,
        "affiliations_service/affiliation_delete.html",
        {"tool": get_tool("as"), "affiliation": affiliation},
    )
