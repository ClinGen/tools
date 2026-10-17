from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render

from auth_.permissions import tool_permission_required
from clinvar_submission_service.models import Submission
from clinvar_submission_service.services import forward_submission
from core.tools import get_tool

# How many submissions the list shows on a page.
PAGE_SIZE = 50

RESEND_FAILED_MESSAGE = (
    "ClinVar still didn't get the submission. Try again in a few minutes, or ask a "
    "developer for help."
)

NOT_RESENDABLE_MESSAGE = "Only a submission ClinVar never got can be resent."


@tool_permission_required("has_css_permissions")
def index(request: HttpRequest) -> HttpResponse:
    """Lists submissions, newest first, optionally searched by slug or ClinVar ID.

    Returns:
        The list page.
    """
    query = request.GET.get("q", "").strip()
    submissions = Submission.objects.select_related("api_key")
    if query:
        submissions = submissions.filter(
            Q(slug__icontains=query) | Q(clinvar_submission_id__icontains=query)
        )
    page = Paginator(submissions, PAGE_SIZE).get_page(request.GET.get("page"))
    return render(
        request,
        "clinvar_submission_service/list.html",
        {"tool": get_tool("css"), "page": page, "query": query},
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
    report = submission.summary_report or {}
    return render(
        request,
        "clinvar_submission_service/detail.html",
        {
            "tool": get_tool("css"),
            "submission": submission,
            "records": report.get("submissions") or [],
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
