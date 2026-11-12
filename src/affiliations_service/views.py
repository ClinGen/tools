"""Houses the AS's pages."""

from django import forms
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django_tables2 import RequestConfig, Table

from affiliations_service.forms import (
    AffiliationCreateForm,
    AffiliationEditForm,
    CDWGForm,
    MembershipAddForm,
    OtherEmailFormSet,
    SubmitterIdFormSet,
    UserForm,
)
from affiliations_service.history import describe_history
from affiliations_service.models import CDWG, Affiliation, Membership, User
from affiliations_service.tables import PER_PAGE, AffiliationTable, CDWGTable, UserTable
from auth_.permissions import tool_permission_required
from common import breadcrumbs as crumbs
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
            "breadcrumbs": [
                crumbs.section("Affiliation Search", "as:index", current=True)
            ],
            "table": _paginated(request, AffiliationTable(affiliations)),
            "query": query,
            "filters": filters,
            "types": Affiliation.Type.choices,
            "statuses": Affiliation.Status.choices,
            "cdwgs": CDWG.objects.all(),
        },
    )


def _paginated(request: HttpRequest, table: Table) -> Table:
    """Sorts and pages a table from the request's sort and page parameters.

    Returns:
        The table, showing one page of `PER_PAGE` rows.
    """
    RequestConfig(request, paginate={"per_page": PER_PAGE}).configure(table)
    return table


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
    memberships = affiliation.memberships.select_related("user")  # ty: ignore[unresolved-attribute] (Django adds the reverse relation.)
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
            "breadcrumbs": [
                crumbs.section("Affiliation Search", "as:index"),
                crumbs.detail(affiliation, current=True),
            ],
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
    """Gives a user a role in an affiliation.

    Returns:
        The updated members section, or the affiliation's page.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    affiliation = get_object_or_404(Affiliation, pk=pk)
    form = MembershipAddForm(request.POST, instance=Membership(affiliation=affiliation))
    if form.is_valid():
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
def user_search(request: HttpRequest) -> HttpResponse:
    """Finds users by name or email for the add-member and new-affiliation forms.

    `input=coordinators` returns checkboxes for the new-affiliation form's coordinators;
    otherwise it returns radio buttons for the add-member form's user.

    Returns:
        Up to ten matching users, as choices for the form.
    """
    query = request.GET.get("q", "").strip()
    users = User.objects.none()
    if query:
        users = User.objects.filter(
            Q(name__icontains=query)
            | Q(preferred_name__icontains=query)
            | Q(email__icontains=query)
            | Q(other_emails__email__icontains=query)
        ).distinct()[:10]
    # The add-member form picks one user; the new-affiliation form picks coordinators.
    input_name = (
        "coordinators" if request.GET.get("input") == "coordinators" else "user"
    )
    return render(
        request,
        "affiliations_service/partials/user_choices.html",
        {"as_users": users, "query": query, "input_name": input_name},
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
            "breadcrumbs": [
                crumbs.section("Affiliation Search", "as:index"),
                *(
                    [crumbs.detail(affiliation), crumbs.action("Edit", "pencil-square")]
                    if affiliation
                    else [crumbs.action("New Affiliation", "plus-circle")]
                ),
            ],
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
        {
            "tool": get_tool("as"),
            "breadcrumbs": [
                crumbs.section("Affiliation Search", "as:index"),
                crumbs.detail(affiliation),
                crumbs.action("Delete", "trash"),
            ],
            "affiliation": affiliation,
        },
    )


@tool_permission_required("has_as_permissions")
def user_list(request: HttpRequest) -> HttpResponse:
    """Lists users, with a search box for names and emails.

    Returns:
        The users list.
    """
    users = User.objects.all()
    query = request.GET.get("q", "").strip()
    if query:
        users = users.filter(
            Q(name__icontains=query)
            | Q(preferred_name__icontains=query)
            | Q(email__icontains=query)
            | Q(other_emails__email__icontains=query)
        ).distinct()
    return render(
        request,
        "affiliations_service/user_list.html",
        {
            "tool": get_tool("as"),
            "breadcrumbs": [crumbs.section("User Search", "as:users", current=True)],
            "table": _paginated(request, UserTable(users)),
            "query": query,
        },
    )


@tool_permission_required("has_as_permissions")
def user_detail(request: HttpRequest, pk: str) -> HttpResponse:
    """Shows a user, their affiliations, and their history.

    Returns:
        The user's page.
    """
    user = get_object_or_404(User.objects.prefetch_related("other_emails"), pk=pk)
    memberships = user.memberships.select_related("affiliation")  # ty: ignore[unresolved-attribute] (Django adds the reverse relation.)
    current = memberships.current()
    return render(
        request,
        "affiliations_service/user_detail.html",
        {
            "tool": get_tool("as"),
            "breadcrumbs": [
                crumbs.section("User Search", "as:users"),
                crumbs.detail(user, current=True),
            ],
            "as_user": user,
            "current_memberships": current,
            "past_memberships": memberships.exclude(pk__in=current).order_by(
                "-end_date"
            ),
            "history": describe_history(user, "the user"),
        },
    )


def _user_form(request: HttpRequest, user: User | None) -> HttpResponse:
    """Shows the user form, and saves the user when the form is valid.

    Returns:
        The form page, or a redirect to the user's page once they're saved.
    """
    data = request.POST if request.method == "POST" else None
    form = UserForm(data, instance=user)
    formset = OtherEmailFormSet(data, instance=user)
    if data is not None and (url := _save_form_and_formset(form, formset)):
        return redirect(url)
    return render(
        request,
        "affiliations_service/user_form.html",
        {
            "tool": get_tool("as"),
            "breadcrumbs": [
                crumbs.section("User Search", "as:users"),
                *(
                    [crumbs.detail(user), crumbs.action("Edit", "pencil-square")]
                    if user
                    else [crumbs.action("New User", "plus-circle")]
                ),
            ],
            "form": form,
            "formset": formset,
            "as_user": user,
        },
    )


@tool_permission_required("has_as_permissions")
def user_create(request: HttpRequest) -> HttpResponse:
    """Adds a user.

    Returns:
        The form, or a redirect to the new user's page.
    """
    return _user_form(request, None)


@tool_permission_required("has_as_permissions")
def user_edit(request: HttpRequest, pk: str) -> HttpResponse:
    """Changes a user.

    Returns:
        The form, or a redirect to the user's page.
    """
    return _user_form(request, get_object_or_404(User, pk=pk))


@tool_permission_required("has_as_permissions")
def cdwg_list(request: HttpRequest) -> HttpResponse:
    """Lists the CDWGs, with how many affiliations each one has.

    `q` searches names. Deleted affiliations aren't counted.

    Returns:
        The CDWG list.
    """
    cdwgs = CDWG.objects.annotate(
        affiliation_count=Count(
            "affiliations", filter=Q(affiliations__is_deleted=False)
        )
    ).order_by("name")
    query = request.GET.get("q", "").strip()
    if query:
        cdwgs = cdwgs.filter(name__icontains=query)
    return render(
        request,
        "affiliations_service/cdwg_list.html",
        {
            "tool": get_tool("as"),
            "breadcrumbs": [crumbs.section("CDWG Search", "as:cdwgs", current=True)],
            "cdwgs": cdwgs,
            "table": _paginated(request, CDWGTable(cdwgs)),
            "query": query,
        },
    )


def _cdwg_form(request: HttpRequest, cdwg: CDWG | None) -> HttpResponse:
    """Shows the CDWG form, and saves the CDWG when the form is valid.

    Returns:
        The form page, or a redirect to the CDWG list once it's saved.
    """
    form = CDWGForm(request.POST if request.method == "POST" else None, instance=cdwg)
    if form.is_valid():
        form.save()
        return redirect("as:cdwgs")
    return render(
        request,
        "affiliations_service/cdwg_form.html",
        {
            "tool": get_tool("as"),
            "breadcrumbs": [
                crumbs.section("CDWG Search", "as:cdwgs"),
                crumbs.action(f"Edit {cdwg}", "pencil-square")
                if cdwg
                else crumbs.action("New CDWG", "plus-circle"),
            ],
            "form": form,
            "cdwg": cdwg,
        },
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
