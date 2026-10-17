"""Serves the CSS's API, version 1, at /css/api/v1/.

Clients authenticate with an API key in the X-API-Key header and see only their own
submissions. The OpenAPI docs are at /css/api/v1/docs.
"""

from datetime import datetime
from typing import Any

from django.db.models import QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Body, NinjaAPI, Schema, Status
from ninja.errors import HttpError
from ninja.pagination import paginate

from clinvar_submission_service.api_auth import ApiKeyAuth
from clinvar_submission_service.models import Submission
from clinvar_submission_service.services import (
    MAX_RECORDS,
    count_records,
    forward_submission,
)

api = NinjaAPI(
    title="ClinVar Submission Service API",
    version="1",
    description=(
        "Forwards ClinVar submissions to ClinVar and tracks each one until ClinVar has "
        "processed it."
    ),
    auth=ApiKeyAuth(),
    # The API is mounted inside the CSS's URLconf, so its namespace is nested in css.
    urls_namespace="css:api-1",
)


class SubmissionSummary(Schema):
    """A submission's status, without ClinVar's responses."""

    slug: str
    status: str
    clinvar_submission_id: str
    clinvar_error_code: int | None
    error_message: str
    added_at: datetime
    updated_at: datetime


class SubmissionDetail(SubmissionSummary):
    """A submission's status and ClinVar's responses."""

    clinvar_updated_at: datetime | None
    latest_response: dict[str, Any] | None
    summary_report: dict[str, Any] | None


@api.post("/submissions", response={201: SubmissionDetail})
def create_submission(
    request: HttpRequest, content: Body[dict[str, Any]]
) -> Status[Submission]:
    """Saves a submission and forwards it to ClinVar.

    The body is the ClinVar submission content; the CSS wraps it in ClinVar's AddData
    action. The response's status is submitted if ClinVar accepted it, or send_failed,
    with an error message, if it didn't.

    Returns:
        201 and the submission.

    Raises:
        HttpError: 422 if the content holds too many records.
    """
    if count_records(content) > MAX_RECORDS:
        error_message = f"A submission can hold at most {MAX_RECORDS} records."
        raise HttpError(422, error_message)
    submission = Submission.objects.create(api_key=request.auth, payload=content)  # ty: ignore[unresolved-attribute] (Ninja sets request.auth.)
    return Status(201, forward_submission(submission))


@api.get("/submissions", response=list[SubmissionSummary])
@paginate
def list_submissions(request: HttpRequest) -> QuerySet[Submission]:
    """Lists the calling client's submissions, newest first.

    Returns:
        The client's submissions, a page at a time.
    """
    return Submission.objects.filter(api_key=request.auth)  # ty: ignore[unresolved-attribute] (Ninja sets request.auth.)


@api.get("/submissions/{slug}", response=SubmissionDetail)
def read_submission(request: HttpRequest, slug: str) -> Submission:
    """Reads one of the calling client's submissions.

    Returns:
        The submission, or 404 if the client has none with that slug.
    """
    return get_object_or_404(Submission, slug=slug, api_key=request.auth)  # ty: ignore[unresolved-attribute] (Ninja sets request.auth.)
