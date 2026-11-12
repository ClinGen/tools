"""Serves the CSS's API, version 1, at /css/api/v1/.

Clients send records one at a time, and staff later send them to ClinVar in batches.
Clients authenticate with an API key in the X-API-Key header and see only their own
records. The OpenAPI docs are at /css/api/v1/docs.
"""

import json
from datetime import datetime
from typing import Any

from django.db.models import QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Field, NinjaAPI, Schema, Status
from ninja.pagination import paginate

from clinvar_submission_service.api.auth import ApiKeyAuth
from clinvar_submission_service.content import Affiliation, RecordRequest
from clinvar_submission_service.models import Record
from clinvar_submission_service.services import (
    NotWithdrawableError,
    save_record,
    withdraw_record,
)

api = NinjaAPI(
    title="ClinVar Submission Service API",
    version="1",
    description=(
        "Holds ClinVar records until staff send them to ClinVar in batches, and "
        "tracks each batch until ClinVar has processed it."
    ),
    auth=ApiKeyAuth(),
    # The API is mounted inside the CSS's URLconf, so its namespace is nested in css.
    urls_namespace="css:api-1",
)


def _affiliation_of(record: Record) -> Affiliation | None:
    """Returns a record's affiliation, or None if it has none."""
    if record.affiliation_id is None:
        return None
    return Affiliation(id=record.affiliation_id, name=record.affiliation_name)


class RecordSummary(Schema):
    """A record's status and the fields that identify it."""

    slug: str
    affiliation: Affiliation | None
    status: str
    tool_id: str
    clinvar_accession: str
    added_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_affiliation(record: Record) -> Affiliation | None:
        """Returns the record's affiliation, if it has one."""
        return _affiliation_of(record)


class RecordDetail(RecordSummary):
    """A record's status and its ClinVar JSON as the client sent it."""

    record: dict[str, Any] = Field(alias="payload")


@api.post("/records", response={200: RecordDetail, 201: RecordDetail})
def create_record(request: HttpRequest, body: RecordRequest) -> Status[Record]:
    """Saves a record to wait in the CSS until staff send it to ClinVar in a batch.

    The body is the client's affiliation and one germline record. If the affiliation
    has a record with the same localID that's still waiting, the CSS replaces it and
    keeps the old version. A body that doesn't match gets a 422.

    Returns:
        201 and the new record, or 200 and the record it replaced.
    """
    # Save the record as sent, not as Ninja parsed it, since that's what's forwarded.
    payload = json.loads(request.body)["record"]
    record, created = save_record(
        api_key=request.auth,  # ty: ignore[unresolved-attribute] (Ninja sets request.auth.)
        affiliation=body.affiliation,
        payload=payload,
    )
    return Status(201 if created else 200, record)


@api.get("/records", response=list[RecordSummary])
@paginate
def list_records(request: HttpRequest) -> QuerySet[Record]:
    """Lists the calling client's records, newest first.

    Returns:
        The client's records, a page at a time.
    """
    return Record.objects.filter(api_key=request.auth).order_by("-added_at")  # ty: ignore[unresolved-attribute] (Ninja sets request.auth.)


@api.get("/records/{slug}", response=RecordDetail)
def read_record(request: HttpRequest, slug: str) -> Record:
    """Reads one of the calling client's records.

    Returns:
        The record, or 404 if the client has none with that slug.
    """
    return get_object_or_404(Record, slug=slug, api_key=request.auth)  # ty: ignore[unresolved-attribute] (Ninja sets request.auth.)


class Error(Schema):
    """Why a request was refused."""

    detail: str


@api.post("/records/{slug}/withdraw", response={200: RecordDetail, 409: Error})
def withdraw(request: HttpRequest, slug: str) -> Record | Status[Error]:
    """Withdraws one of the calling client's waiting records.

    A withdrawn record won't be sent to ClinVar. A record that's in a batch, or that
    ClinVar accepted, can't be withdrawn and gets a 409.

    Returns:
        The record, 404 if the client has none with that slug, or 409.
    """
    api_key = request.auth  # ty: ignore[unresolved-attribute] (Ninja sets request.auth.)
    record = get_object_or_404(Record, slug=slug, api_key=api_key)
    try:
        return withdraw_record(record, by=f"the {api_key.name}")
    except NotWithdrawableError as error:
        return Status(409, Error(detail=str(error)))
