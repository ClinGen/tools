from dataclasses import dataclass
from urllib.parse import urlencode

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Q, QuerySet, Subquery
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from auth_.permissions import tool_permission_required
from clinvar_submission_service.models import Record, Submission
from clinvar_submission_service.services import forward_submission
from core.tools import get_tool

# How many submissions the list shows on a page.
PAGE_SIZE = 50

RESEND_FAILED_MESSAGE = (
    "ClinVar still didn't get the submission. Try again in a few minutes, or ask a "
    "developer for help."
)

NOT_RESENDABLE_MESSAGE = "Only a submission ClinVar never got can be resent."

# The list's filters, by their sent= value: submissions ClinVar never got, and ones it
# did. Any other value shows every submission.
NOT_SENT_STATUSES = [Submission.Status.RECEIVED, Submission.Status.SEND_FAILED]
SENT_FILTERS = {
    "not_sent": Q(status__in=NOT_SENT_STATUSES),
    "sent": ~Q(status__in=NOT_SENT_STATUSES),
}

# The counts on the affiliations page, by the name each row's count has.
AFFILIATION_COUNTS = {
    "not_sent": Q(status__in=NOT_SENT_STATUSES),
    "waiting": Q(status__in=Submission.POLLABLE_STATUSES),
    "accepted": Q(status=Submission.Status.PROCESSED),
    "errors": Q(status=Submission.Status.ERROR),
}


def _query_string(**params: str) -> str:
    """Returns a query string with the params that have values, starting with ?."""
    return "?" + urlencode({name: value for name, value in params.items() if value})


def _filter_by_affiliation(
    submissions: QuerySet[Submission], affiliation: str
) -> QuerySet[Submission]:
    """Returns the submissions from the affiliation, or none if it isn't an ID."""
    try:
        return submissions.filter(affiliation_id=int(affiliation))
    except ValueError:
        return submissions.none()


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


def _record_rows(submission: Submission) -> list[RecordRow]:
    """Returns the submission's records, each with ClinVar's result, if any."""
    report = submission.summary_report or {}
    results = {
        (result.get("identifiers") or {}).get("localID"): result
        for result in report.get("submissions") or []
    }
    rows = []
    for record in submission.records.all():  # type: ignore
        result = results.get(record.local_id)
        if result is None:
            rows.append(RecordRow(record=record, accepted=None, scv=""))
            continue
        scv = (result.get("identifiers") or {}).get("clinvarAccession") or ""
        accepted = result.get("processingStatus") == "Success"
        rows.append(RecordRow(record=record, accepted=accepted, scv=scv))
    return rows


@tool_permission_required("has_css_permissions")
def index(request: HttpRequest) -> HttpResponse:
    """Lists submissions, newest first.

    The sent= filter narrows the list to submissions ClinVar never got or ones it did,
    and the affiliation= filter to one affiliation's, by its ID. The q= search matches
    a submission's ID, ClinVar ID, or affiliation, or a record's gene or HGVS.

    Returns:
        The list page.
    """
    query = request.GET.get("q", "").strip()
    sent = request.GET.get("sent", "")
    if sent not in SENT_FILTERS:
        sent = ""
    submissions = Submission.objects.select_related("api_key").prefetch_related(
        "records"
    )
    affiliation = request.GET.get("affiliation", "").strip()
    affiliation_name = ""
    if affiliation:
        submissions = _filter_by_affiliation(submissions, affiliation)
        newest = submissions.first()
        affiliation_name = newest.affiliation_name if newest else ""
    if sent:
        submissions = submissions.filter(SENT_FILTERS[sent])
    if query:
        matches = (
            Q(slug__icontains=query)
            | Q(clinvar_submission_id__icontains=query)
            | Q(affiliation_name__icontains=query)
            | Q(records__gene_symbol__icontains=query)
            | Q(records__hgvs__icontains=query)
        )
        submissions = submissions.filter(matches).distinct()
    page = Paginator(submissions, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "clinvar_submission_service/list.html",
        {
            "tool": get_tool("css"),
            "page": page,
            "query": query,
            "sent": sent,
            "affiliation": affiliation,
            "affiliation_name": affiliation_name,
            "filter_links": [
                (label, value, _query_string(affiliation=affiliation, sent=value))
                for label, value in (
                    ("All", ""),
                    ("Not Sent to ClinVar", "not_sent"),
                    ("Sent to ClinVar", "sent"),
                )
            ],
            "page_query": _query_string(q=query, sent=sent, affiliation=affiliation),
        },
    )


@tool_permission_required("has_css_permissions")
def affiliations(request: HttpRequest) -> HttpResponse:
    """Lists each affiliation that has submissions, with counts by status.

    An affiliation's name is the one on its newest submission, in case it changed.

    Returns:
        The affiliations page.
    """
    newest_name = (
        Submission.objects.filter(affiliation_id=OuterRef("affiliation_id"))
        .order_by("-added_at")
        .values("affiliation_name")[:1]
    )
    counts = {name: Count("pk", filter=q) for name, q in AFFILIATION_COUNTS.items()}
    rows = (
        # Clear the default ordering, which would split the groups.
        Submission.objects.order_by()
        .filter(affiliation_id__isnull=False)
        .values("affiliation_id")
        .annotate(name=Subquery(newest_name), total=Count("pk"), **counts)
        .order_by("name")
    )
    return render(
        request,
        "clinvar_submission_service/affiliations.html",
        {"tool": get_tool("css"), "affiliations": rows},
    )


@tool_permission_required("has_css_permissions")
def submission_detail(request: HttpRequest, slug: str) -> HttpResponse:
    """Shows a submission's status and each record's result.

    Returns:
        The detail page.
    """
    submission = get_object_or_404(
        Submission.objects.select_related("api_key"), slug=slug
    )
    return render(
        request,
        "clinvar_submission_service/detail.html",
        {
            "tool": get_tool("css"),
            "submission": submission,
            "rows": _record_rows(submission),
        },
    )


@tool_permission_required("has_css_permissions")
def resend(request: HttpRequest, slug: str) -> HttpResponse:
    """Sends a submission ClinVar never got to ClinVar again.

    Returns:
        A redirect to the submission's page, or 405 if the request isn't a POST.
    """
    if request.method != "POST":
        return HttpResponseNotAllowed(["POST"])
    submission = get_object_or_404(Submission, slug=slug)
    if submission.status != Submission.Status.SEND_FAILED:
        messages.error(request, NOT_RESENDABLE_MESSAGE)
    elif forward_submission(submission).status == Submission.Status.SEND_FAILED:
        messages.error(request, RESEND_FAILED_MESSAGE)
    return redirect(submission)
