from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.models import User
from django.db.models import Count, Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django_tables2 import RequestConfig

from auth_.permissions import tool_permission_required
from clinvar_submission_service.forms import AffiliationSettingsForm
from clinvar_submission_service.models import AffiliationSettings, Batch, Record
from clinvar_submission_service.services import (
    BatchNotMadeError,
    NotWithdrawableError,
    check_batchable,
    forward_batch,
    make_batch,
    report_results,
    withdraw_record,
)
from clinvar_submission_service.simulation import (
    delete_all_batches,
    delete_all_records,
)
from clinvar_submission_service.tables import BatchTable, RecordTable
from common import breadcrumbs as crumbs
from core.tools import get_tool

# How many batches the list shows on a page.
PAGE_SIZE = 50

RESEND_FAILED_MESSAGE = (
    "ClinVar still didn't get the batch. Try again in a few minutes, or ask a "
    "developer for help."
)

NOT_RESENDABLE_MESSAGE = "Only a batch ClinVar never got can be resent."

WITHDRAWN_MESSAGE = "The record was withdrawn."

# Each navbar section's list page, as its breadcrumb's text, URL name, and icon.
SECTIONS = {
    "records": ("Records", "css:records", "list-ul"),
    "batches": ("Batches", "css:batches", "card-list"),
    "affiliations": ("Affiliations", "css:affiliations", "people"),
}


def _section(name: str, *, current: bool = False) -> crumbs.Crumb:
    """Returns the breadcrumb for a navbar section's list page.

    Args:
        name: The section's key in `SECTIONS`.
        current: Whether the list page is the current page.

    Returns:
        The crumb.
    """
    return crumbs.section(*SECTIONS[name], current=current)


def _query_string(**params: str) -> str:
    """Returns a query string with the params that have values, starting with ?."""
    return "?" + urlencode({name: value for name, value in params.items() if value})


def _filter_by_affiliation[T: (Batch, Record)](
    rows: QuerySet[T], affiliation: str
) -> QuerySet[T]:
    """Returns the rows from the affiliation, or none if it isn't an ID."""
    try:
        return rows.filter(affiliation_id=int(affiliation))
    except ValueError:
        return rows.none()


@dataclass(frozen=True)
class RecordRow:
    """A record and ClinVar's result for it, if ClinVar has reported one.

    Attributes:
        record: The record.
        accepted: Whether ClinVar accepted the record, or None until it reports.
        scv: The SCV accession ClinVar gave the record, if any.
    """

    record: Record
    accepted: bool | None
    scv: str


def _record_rows(batch: Batch) -> list[RecordRow]:
    """Returns the batch's records, each with ClinVar's result, if any."""
    results = report_results(batch.summary_report)
    rows = []
    attempts = batch.batch_records.select_related("record")  # type: ignore
    for record in (attempt.record for attempt in attempts):
        result = results.get(record.local_id)
        if result is None:
            rows.append(RecordRow(record=record, accepted=None, scv=""))
            continue
        scv = (result.get("identifiers") or {}).get("clinvarAccession") or ""
        accepted = result.get("processingStatus") == "Success"
        rows.append(RecordRow(record=record, accepted=accepted, scv=scv))
    return rows


@tool_permission_required("has_css_permissions")
def batches(request: HttpRequest) -> HttpResponse:
    """Lists batches, newest first.

    The status= filter narrows the list to one status, such as submitted_to_clinvar,
    and the affiliation= filter to one affiliation's, by its ID. An unknown status
    shows every batch. The q= search matches
    a batch's ID, ClinVar ID, or affiliation, or a record's gene or HGVS. The
    table's sort= and page= parameters sort and page the results.

    Returns:
        The list page, or just its results for an HTMX request, which the search box
        and the table's links send.
    """
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if status not in Batch.Status.values:
        status = ""
    batches = Batch.objects.select_related("made_by").prefetch_related("records")
    affiliation = request.GET.get("affiliation", "").strip()
    if affiliation:
        batches = _filter_by_affiliation(batches, affiliation)
    if status:
        batches = batches.filter(status=status)
    if query:
        matches = (
            Q(slug__icontains=query)
            | Q(clinvar_submission_id__icontains=query)
            | Q(affiliation_name__icontains=query)
            | Q(records__gene_symbol__icontains=query)
            | Q(records__hgvs__icontains=query)
        )
        batches = batches.filter(matches).distinct()
    table = BatchTable(batches, affiliation=affiliation)
    RequestConfig(request, paginate={"per_page": PAGE_SIZE}).configure(table)
    template = (
        "clinvar_submission_service/partials/results.html"
        if request.headers.get("HX-Request")
        else "clinvar_submission_service/list.html"
    )
    return render(
        request,
        template,
        {
            "tool": get_tool("css"),
            "table": table,
            "query": query,
            "status": status,
            **_affiliation_filter(affiliation),
            "filter_links": [
                (label, value, _query_string(affiliation=affiliation, status=value))
                for value, label in [("", "All"), *Batch.Status.choices]
            ],
            "breadcrumbs": [_section("batches", current=True)],
        },
    )


def _affiliation_names() -> dict[int, str]:
    """Returns each known affiliation's name, by ID.

    A name is the one on the affiliation's newest record, or on its newest batch if it
    has no records, in case it changed.
    """
    names: dict[int, str] = {}
    for model in (Record, Batch):
        rows = (
            model.objects.filter(affiliation_id__isnull=False)
            .order_by("affiliation_id", "-added_at")
            .values_list("affiliation_id", "affiliation_name")
        )
        for affiliation_id, name in rows:
            names.setdefault(affiliation_id, name)
    return names


def _affiliation_filter(affiliation: str) -> dict[str, object]:
    """Returns the context for a list's affiliation select and New Batch button.

    Args:
        affiliation: The list's affiliation= filter, if any.
    """
    names = _affiliation_names()
    try:
        affiliation_id = int(affiliation) if affiliation else None
    except ValueError:
        affiliation_id = -1
    has_waiting = (
        affiliation_id in names
        and Record.objects.filter(
            affiliation_id=affiliation_id, status=Record.Status.WAITING_FOR_BATCH
        ).exists()
    )
    return {
        "affiliation": affiliation,
        "affiliations": sorted(names.items(), key=lambda item: item[1]),
        "unknown_affiliation": affiliation_id is not None
        and affiliation_id not in names,
        "new_batch_affiliation": affiliation_id if has_waiting else None,
    }


@tool_permission_required("has_css_permissions")
def records(request: HttpRequest) -> HttpResponse:
    """Lists every record, newest first.

    The status= filter shows only records in one status, and the affiliation= filter
    one affiliation's, by its ID. An unknown status shows every record. The q= search
    matches a record's gene, HGVS, local ID, or affiliation. The table's sort= and
    page= parameters sort and page the results.

    Returns:
        The records page, or just its results for an HTMX request.
    """
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if status not in Record.Status.values:
        status = ""
    rows = Record.objects.order_by("-added_at")
    affiliation = request.GET.get("affiliation", "").strip()
    if affiliation:
        rows = _filter_by_affiliation(rows, affiliation)
    if status:
        rows = rows.filter(status=status)
    if query:
        rows = rows.filter(
            Q(gene_symbol__icontains=query)
            | Q(hgvs__icontains=query)
            | Q(local_id__icontains=query)
            | Q(affiliation_name__icontains=query)
        )
    table = RecordTable(rows, affiliation=affiliation)
    RequestConfig(request, paginate={"per_page": PAGE_SIZE}).configure(table)
    template = (
        "clinvar_submission_service/partials/record_results.html"
        if request.headers.get("HX-Request")
        else "clinvar_submission_service/records.html"
    )
    return render(
        request,
        template,
        {
            "tool": get_tool("css"),
            "table": table,
            "query": query,
            "status": status,
            **_affiliation_filter(affiliation),
            "filter_links": [
                (label, value, _query_string(affiliation=affiliation, status=value))
                for value, label in [("", "All"), *Record.Status.choices]
            ],
            "breadcrumbs": [_section("records", current=True)],
        },
    )


def _counts_by_status(
    model: type[Batch] | type[Record],
) -> dict[int, dict[str, int]]:
    """Returns how many of the model's rows each affiliation has, by status."""
    counts: dict[int, dict[str, int]] = {}
    rows = (
        model.objects.order_by()  # Clear the ordering, which would split the groups.
        .filter(affiliation_id__isnull=False)
        .values_list("affiliation_id", "status")
        .annotate(count=Count("pk"))
    )
    for affiliation_id, status, count in rows:
        counts.setdefault(affiliation_id, {})[status] = count
    return counts


def _pill_counts(
    url: str,
    affiliation_id: int,
    choices: Iterable[tuple[str, object]],
    counts: dict[str, int],
) -> list[tuple[str, int, str]]:
    """Returns each of a list's pills, with its count and link, for one affiliation.

    Returns:
        A (label, count, link) per pill: All, then one per status.
    """
    pills = [("All", sum(counts.values()), "")]
    pills += [(str(label), counts.get(value, 0), value) for value, label in choices]
    return [
        (
            label,
            count,
            url + _query_string(affiliation=str(affiliation_id), status=value),
        )
        for label, count, value in pills
    ]


@tool_permission_required("has_css_permissions")
def affiliations(request: HttpRequest) -> HttpResponse:
    """Lists each affiliation with records or batches, counted like each list's pills.

    Returns:
        The affiliations page.
    """
    record_counts = _counts_by_status(Record)
    batch_counts = _counts_by_status(Batch)
    rows = [
        {
            "affiliation_id": affiliation_id,
            "name": name,
            "records": _pill_counts(
                reverse("css:records"),
                affiliation_id,
                Record.Status.choices,
                record_counts.get(affiliation_id, {}),
            ),
            "batches": _pill_counts(
                reverse("css:batches"),
                affiliation_id,
                Batch.Status.choices,
                batch_counts.get(affiliation_id, {}),
            ),
        }
        for affiliation_id, name in _affiliation_names().items()
    ]
    return render(
        request,
        "clinvar_submission_service/affiliations.html",
        {
            "tool": get_tool("css"),
            "record_pills": ["All", *Record.Status.labels],
            "batch_pills": ["All", *Batch.Status.labels],
            "affiliations": sorted(rows, key=lambda row: row["name"]),
            "breadcrumbs": [_section("affiliations", current=True)],
        },
    )


@tool_permission_required("has_css_permissions")
def batch_detail(request: HttpRequest, slug: str) -> HttpResponse:
    """Shows a batch's status and each record's result.

    Returns:
        The detail page.
    """
    batch = get_object_or_404(Batch.objects.select_related("made_by"), slug=slug)
    return render(
        request,
        "clinvar_submission_service/detail.html",
        {
            "tool": get_tool("css"),
            "batch": batch,
            "rows": _record_rows(batch),
            "breadcrumbs": [
                _section("batches"),
                crumbs.action(f"{batch.slug} Details", "journal-text"),
            ],
        },
    )


@tool_permission_required("has_css_permissions")
def resend(request: HttpRequest, slug: str) -> HttpResponse:
    """Sends a batch ClinVar never got to ClinVar again.

    Returns:
        A redirect to the batch's page, or 405 if the request isn't a POST.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    batch = get_object_or_404(Batch, slug=slug)
    if batch.status != Batch.Status.SEND_TO_CLINVAR_FAILED:
        messages.error(request, NOT_RESENDABLE_MESSAGE)
    elif forward_batch(batch).status == Batch.Status.SEND_TO_CLINVAR_FAILED:
        messages.error(request, RESEND_FAILED_MESSAGE)
    return redirect(batch)


@dataclass(frozen=True)
class HistoryRow:
    """One change to a record, in plain words.

    Attributes:
        when: When it happened.
        what: What happened.
        who: The staff member who did it, if one did.
    """

    when: datetime
    what: str
    who: str


def _history_rows(record: Record) -> list[HistoryRow]:
    """Returns the record's changes, oldest first, in plain words."""
    rows = []
    previous = None
    history = record.history.select_related("history_user").order_by("history_date")  # type: ignore
    for entry in history:
        if entry.history_change_reason:
            what = entry.history_change_reason
        elif previous is None:
            client = entry.api_key.name if entry.api_key_id else ""
            what = f"Received from the {client}" if client else "Received"
        elif entry.status != previous.status:
            what = f"Became {Record.Status(entry.status).label}"
        else:
            what = "Replaced by a new version from the client"
        user = entry.history_user
        rows.append(
            HistoryRow(
                when=entry.history_date, what=what, who=user.email if user else ""
            )
        )
        previous = entry
    return rows


@tool_permission_required("has_css_permissions")
def record_detail(request: HttpRequest, slug: str) -> HttpResponse:
    """Shows a record's fields, status, attempts in batches, and history.

    Returns:
        The record's page.
    """
    record = get_object_or_404(Record.objects.select_related("api_key"), slug=slug)
    attempts = record.batch_records.select_related("batch").order_by("added_at")  # type: ignore
    return render(
        request,
        "clinvar_submission_service/record.html",
        {
            "tool": get_tool("css"),
            "record": record,
            "attempts": attempts,
            "history": _history_rows(record),
            "breadcrumbs": [
                _section("records"),
                crumbs.action(f"{record.slug} Details", "journal-text"),
            ],
        },
    )


@tool_permission_required("has_css_permissions")
def withdraw(request: HttpRequest, slug: str) -> HttpResponse:
    """Withdraws a waiting record, so it won't be sent to ClinVar.

    Returns:
        A redirect to the record's page, or 405 if the request isn't a POST.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    record = get_object_or_404(Record, slug=slug)
    try:
        withdraw_record(record, by="staff")
    except NotWithdrawableError as error:
        messages.error(request, str(error))
    else:
        messages.success(request, WITHDRAWN_MESSAGE)
    return redirect(record)


def _check_simulated_post(request: HttpRequest) -> HttpResponse | None:
    """Returns 405 unless the request is a POST.

    Raises:
        Http404: Unless ClinVar is simulated, so real data can't be deleted.
    """
    if not settings.CSS_SIMULATE_CLINVAR:
        raise Http404
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    return None


@tool_permission_required("has_css_permissions")
def delete_records(request: HttpRequest) -> HttpResponse:
    """Deletes every record and batch while ClinVar is simulated.

    Returns:
        A redirect to the records list, or 405 if the request isn't a POST.
    """
    if refused := _check_simulated_post(request):
        return refused
    count = delete_all_records()
    messages.success(request, f"Deleted {count} records and every batch.")
    return redirect("css:records")


@tool_permission_required("has_css_permissions")
def delete_batches(request: HttpRequest) -> HttpResponse:
    """Deletes every batch while ClinVar is simulated, so their records wait again.

    Returns:
        A redirect to the batches list, or 405 if the request isn't a POST.
    """
    if refused := _check_simulated_post(request):
        return refused
    count = delete_all_batches()
    messages.success(
        request, f"Deleted {count} batches. Their records are waiting again."
    )
    return redirect("css:batches")


def _affiliation_name(affiliation_id: int) -> str:
    """Returns an affiliation's name from its newest record, or else its newest batch.

    Raises:
        Http404: If the CSS has no batch or record from the affiliation.
    """
    for model in (Record, Batch):
        newest = (
            model.objects.filter(affiliation_id=affiliation_id)
            .order_by("-added_at")
            .values_list("affiliation_name", flat=True)
            .first()
        )
        if newest is not None:
            return newest
    raise Http404


@tool_permission_required("has_css_permissions")
def affiliation_settings(request: HttpRequest, affiliation_id: int) -> HttpResponse:
    """Shows and saves the ClinVar settings an affiliation's batches use.

    Returns:
        The settings page, or a redirect to it once the settings are saved.
    """
    name = _affiliation_name(affiliation_id)
    instance = AffiliationSettings.objects.filter(
        affiliation_id=affiliation_id
    ).first() or AffiliationSettings(affiliation_id=affiliation_id)
    form = AffiliationSettingsForm(request.POST or None, instance=instance)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, f"Saved the settings for {name}.")
        return redirect("css:affiliation_settings", affiliation_id=affiliation_id)
    return render(
        request,
        "clinvar_submission_service/affiliation_settings.html",
        {
            "tool": get_tool("css"),
            "affiliation_name": name,
            "form": form,
            "breadcrumbs": [
                _section("affiliations"),
                crumbs.action(f"{name} Settings", "gear"),
            ],
        },
    )


def _chosen_records(slugs: list[str]) -> list[Record]:
    """Returns the records with the slugs, in their order.

    Raises:
        BatchNotMadeError: If a slug isn't a record's.
    """
    by_slug = Record.objects.in_bulk(slugs, field_name="slug")
    if len(by_slug) != len(set(slugs)):
        error_message = "Some of the chosen records couldn't be found."
        raise BatchNotMadeError(error_message)
    return [by_slug[slug] for slug in dict.fromkeys(slugs)]


@tool_permission_required("has_css_permissions")
def new_batch(request: HttpRequest, affiliation_id: int) -> HttpResponse:
    """Makes a batch of an affiliation's waiting records and sends it to ClinVar.

    A GET lists the waiting records to pick. A POST's action= says what to do with
    the records= picked: review shows them before sending, review_all reviews every
    waiting record, and send makes the batch and sends it.

    Returns:
        The page, or a redirect to the new batch's page once it's sent.
    """
    name = _affiliation_name(affiliation_id)
    waiting = Record.objects.filter(
        affiliation_id=affiliation_id, status=Record.Status.WAITING_FOR_BATCH
    )
    chosen: list[Record] = []
    if request.method == "POST":
        action = request.POST.get("action")
        try:
            if action == "review_all":
                chosen = list(waiting)
            else:
                chosen = _chosen_records(request.POST.getlist("records"))
            check_batchable(chosen)
            if action == "send":
                made_by = request.user if isinstance(request.user, User) else None
                batch = forward_batch(make_batch(chosen, made_by=made_by))
                if batch.status == Batch.Status.SEND_TO_CLINVAR_FAILED:
                    messages.error(request, RESEND_FAILED_MESSAGE)
                return redirect(batch)
        except BatchNotMadeError as error:
            messages.error(request, str(error))
            chosen = []
    return render(
        request,
        "clinvar_submission_service/new_batch.html",
        {
            "tool": get_tool("css"),
            "affiliation_name": name,
            "records": chosen or waiting,
            "reviewing": bool(chosen),
            "breadcrumbs": [
                _section("records"),
                crumbs.action("New Batch", "plus-circle"),
            ],
        },
    )
