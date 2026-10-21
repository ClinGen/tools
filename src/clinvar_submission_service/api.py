"""Serves the CSS's API, version 1, at /css/api/v1/.

Clients authenticate with an API key in the X-API-Key header and see only their own
submissions. The OpenAPI docs are at /css/api/v1/docs.
"""

import json
from datetime import datetime
from typing import Any

from django.db.models import QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import NinjaAPI, Schema, Status
from ninja.pagination import paginate

from clinvar_submission_service.api_auth import ApiKeyAuth
from clinvar_submission_service.content import Affiliation, SubmissionRequest
from clinvar_submission_service.models import Submission
from clinvar_submission_service.services import forward_submission, save_submission

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
    affiliation: Affiliation | None
    status: str
    clinvar_submission_id: str
    clinvar_error_code: int | None
    error_message: str
    added_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_affiliation(submission: Submission) -> Affiliation | None:
        """Returns the submission's affiliation, if it has one.

        Returns:
            The affiliation, or None for a submission saved before affiliations.
        """
        if submission.affiliation_id is None:
            return None
        return Affiliation(
            id=submission.affiliation_id, name=submission.affiliation_name
        )


class SubmissionDetail(SubmissionSummary):
    """A submission's status and ClinVar's responses."""

    clinvar_updated_at: datetime | None
    latest_response: dict[str, Any] | None
    summary_report: dict[str, Any] | None


@api.post("/submissions", response={201: SubmissionDetail})
def create_submission(
    request: HttpRequest, body: SubmissionRequest
) -> Status[Submission]:
    """Saves a submission and forwards it to ClinVar.

    The body is the client's affiliation and the ClinVar content, which holds germline
    records. The CSS wraps the content in ClinVar's AddData action and forwards it as
    sent. A body that doesn't match gets a 422. The response's status is
    submitted_to_clinvar if ClinVar accepted it, or send_to_clinvar_failed, with an
    error message, if it didn't.

    Returns:
        201 and the submission.
    """
    # Save the content as sent, not as Ninja parsed it, since that's what's forwarded.
    payload = json.loads(request.body)["content"]
    submission = save_submission(
        api_key=request.auth,  # ty: ignore[unresolved-attribute] (Ninja sets request.auth.)
        affiliation=body.affiliation,
        payload=payload,
    )
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
