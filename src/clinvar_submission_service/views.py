from dataclasses import dataclass

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
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

    The sent= filter narrows the list to submissions ClinVar never got or ones it did.
    The q= search matches a submission's ID, ClinVar ID, or affiliation, or a record's
    gene or HGVS.

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
        {"tool": get_tool("css"), "page": page, "query": query, "sent": sent},
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
