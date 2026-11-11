"""Houses the AS's pages."""

from django import forms
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from affiliations_service.forms import (
    AffiliationCreateForm,
    AffiliationEditForm,
    CdwgForm,
    MembershipAddForm,
    OtherEmailFormSet,
    PersonForm,
    SubmitterIdFormSet,
)
from affiliations_service.history import describe_history
from affiliations_service.models import CDWG, Affiliation, Membership, Person
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


def _members_context(
    affiliation: Affiliation, member_form: MembershipAddForm | None = None
) -> dict:
    """Returns what the members section of an affiliation's page needs.

    Args:
        affiliation: The affiliation.
        member_form: The add-member form, with its errors, or None for a blank one.

    Returns:
        The current members by role, the past memberships, and the add-member form.
    """
    memberships = affiliation.memberships.select_related("person")  # ty: ignore[unresolved-attribute] (Django adds the reverse relation.)
    current = memberships.current()
    return {
        "affiliation": affiliation,
        "members_by_role": [
            (label, [m for m in current if m.role == role])
            for role, label in Membership.Role.choices
        ],
        "past_memberships": memberships.exclude(pk__in=current).order_by("-end_date"),
        "member_form": member_form or MembershipAddForm(),
    }


def _render_affiliation(
    request: HttpRequest,
    affiliation: Affiliation,
    member_form: MembershipAddForm | None = None,
) -> HttpResponse:
    """Renders an affiliation's page.

    Returns:
        The page, with the add-member form's errors if there are any.
    """
    return render(
        request,
        "affiliations_service/affiliation_detail.html",
        {
            "tool": get_tool("as"),
            "history": describe_history(affiliation, "the affiliation"),
            **_members_context(affiliation, member_form),
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
    return _render_affiliation(request, affiliation)


def _members_response(
    request: HttpRequest,
    affiliation: Affiliation,
    member_form: MembershipAddForm | None = None,
) -> HttpResponse:
    """Responds to a change to an affiliation's members.

    HTMX requests get the updated members section. Other requests are redirected to
    the affiliation's page, or shown it with the form's errors.

    Returns:
        The members section, the affiliation's page, or a redirect to it.
    """
    if request.headers.get("HX-Request"):
        return render(
            request,
            "affiliations_service/partials/members.html",
            _members_context(affiliation, member_form),
        )
    if member_form is not None and member_form.errors:
        return _render_affiliation(request, affiliation, member_form)
    return redirect(affiliation)


@tool_permission_required("has_as_permissions")
def membership_add(request: HttpRequest, pk: str) -> HttpResponse:
    """Gives a person a role in an affiliation.

    Returns:
        The updated members section, or the affiliation's page.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    affiliation = get_object_or_404(Affiliation, pk=pk)
    form = MembershipAddForm(request.POST, instance=Membership(affiliation=affiliation))
    if affiliation.is_deleted:
        form.add_error(None, "This affiliation has been deleted.")
    elif form.is_valid():
        form.save()
        return _members_response(request, affiliation)
    return _members_response(request, affiliation, form)


@tool_permission_required("has_as_permissions")
def membership_end(request: HttpRequest, pk: str) -> HttpResponse:
    """Ends a membership today. It's kept, and shown under past members.

    Returns:
        The updated members section, or a redirect to the affiliation's page.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    membership = get_object_or_404(
        Membership.objects.select_related("affiliation"), pk=pk
    )
    membership.end()
    return _members_response(request, membership.affiliation)


@tool_permission_required("has_as_permissions")
def person_search(request: HttpRequest) -> HttpResponse:
    """Finds people by name or email for the add-member form.

    Returns:
        Up to ten matching people, as choices for the form.
    """
    query = request.GET.get("q", "").strip()
    people = Person.objects.none()
    if query:
        people = Person.objects.filter(
            Q(name__icontains=query)
            | Q(preferred_name__icontains=query)
            | Q(email__icontains=query)
            | Q(other_emails__email__icontains=query)
        ).distinct()[:10]
    return render(
        request,
        "affiliations_service/partials/person_choices.html",
        {"people": people, "query": query},
    )


def _save_form_and_formset(
    form: forms.ModelForm, formset: forms.BaseInlineFormSet
) -> str | None:
    """Saves an object and its inline formset if both are valid.

    The formset's rows need the saved object, so it's checked after the object is
    saved, and the save is rolled back if it isn't valid.

    Returns:
        The saved object's URL, or None if the form or the formset has errors.
    """
    if not form.is_valid():
        return None
    adding = form.instance._state.adding  # ruff: ignore[private-member-access]
    with transaction.atomic():
        saved = form.save()
        formset.instance = saved
        if formset.is_valid():
            formset.save()
            return saved.get_absolute_url()
        transaction.set_rollback(True)
    if adding:
        # The rolled-back object was never saved, so the form can try again.
        form.instance._state.adding = True  # ruff: ignore[private-member-access]
    return None


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
    if data is not None and (url := _save_form_and_formset(form, formset)):
        return redirect(url)
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


@tool_permission_required("has_as_permissions")
def person_list(request: HttpRequest) -> HttpResponse:
    """Lists people, with a search box for names and emails.

    Returns:
        The people list.
    """
    people = Person.objects.all()
    query = request.GET.get("q", "").strip()
    if query:
        people = people.filter(
            Q(name__icontains=query)
            | Q(preferred_name__icontains=query)
            | Q(email__icontains=query)
            | Q(other_emails__email__icontains=query)
        ).distinct()
    return render(
        request,
        "affiliations_service/person_list.html",
        {"tool": get_tool("as"), "people": people, "query": query},
    )


@tool_permission_required("has_as_permissions")
def person_detail(request: HttpRequest, pk: str) -> HttpResponse:
    """Shows a person, their affiliations, and their history.

    Returns:
        The person's page.
    """
    person = get_object_or_404(Person.objects.prefetch_related("other_emails"), pk=pk)
    memberships = person.memberships.select_related("affiliation")  # ty: ignore[unresolved-attribute] (Django adds the reverse relation.)
    current = memberships.current()
    return render(
        request,
        "affiliations_service/person_detail.html",
        {
            "tool": get_tool("as"),
            "person": person,
            "current_memberships": current,
            "past_memberships": memberships.exclude(pk__in=current).order_by(
                "-end_date"
            ),
            "history": describe_history(person, "the person"),
        },
    )


def _person_form(request: HttpRequest, person: Person | None) -> HttpResponse:
    """Shows the person form, and saves the person when the form is valid.

    Returns:
        The form page, or a redirect to the person's page once they're saved.
    """
    data = request.POST if request.method == "POST" else None
    form = PersonForm(data, instance=person)
    formset = OtherEmailFormSet(data, instance=person)
    if data is not None and (url := _save_form_and_formset(form, formset)):
        return redirect(url)
    return render(
        request,
        "affiliations_service/person_form.html",
        {"tool": get_tool("as"), "form": form, "formset": formset, "person": person},
    )


@tool_permission_required("has_as_permissions")
def person_create(request: HttpRequest) -> HttpResponse:
    """Adds a person.

    Returns:
        The form, or a redirect to the new person's page.
    """
    return _person_form(request, None)


@tool_permission_required("has_as_permissions")
def person_edit(request: HttpRequest, pk: str) -> HttpResponse:
    """Changes a person.

    Returns:
        The form, or a redirect to the person's page.
    """
    return _person_form(request, get_object_or_404(Person, pk=pk))


@tool_permission_required("has_as_permissions")
def cdwg_list(request: HttpRequest) -> HttpResponse:
    """Lists the CDWGs, with how many affiliations each one has.

    Deleted affiliations aren't counted.

    Returns:
        The CDWG list.
    """
    cdwgs = CDWG.objects.annotate(
        affiliation_count=Count(
            "affiliations", filter=Q(affiliations__is_deleted=False)
        )
    ).order_by("name")
    return render(
        request,
        "affiliations_service/cdwg_list.html",
        {"tool": get_tool("as"), "cdwgs": cdwgs},
    )


def _cdwg_form(request: HttpRequest, cdwg: CDWG | None) -> HttpResponse:
    """Shows the CDWG form, and saves the CDWG when the form is valid.

    Returns:
        The form page, or a redirect to the CDWG list once it's saved.
    """
    form = CdwgForm(request.POST if request.method == "POST" else None, instance=cdwg)
    if form.is_valid():
        form.save()
        return redirect("as:cdwgs")
    return render(
        request,
        "affiliations_service/cdwg_form.html",
        {"tool": get_tool("as"), "form": form, "cdwg": cdwg},
    )


@tool_permission_required("has_as_permissions")
def cdwg_create(request: HttpRequest) -> HttpResponse:
    """Adds a CDWG.

    Returns:
        The form, or a redirect to the CDWG list.
    """
    return _cdwg_form(request, None)


@tool_permission_required("has_as_permissions")
def cdwg_edit(request: HttpRequest, pk: str) -> HttpResponse:
    """Changes a CDWG.

    Returns:
        The form, or a redirect to the CDWG list.
    """
    return _cdwg_form(request, get_object_or_404(CDWG, pk=pk))
