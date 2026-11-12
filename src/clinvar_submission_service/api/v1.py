"""Serves the CSS's API, version 1, at /css/api/v1/.

Clients send records one at a time, and staff later send them to ClinVar in batches.
Clients authenticate with an API key in the X-API-Key header and see only their own
records, and the batches that hold them. The OpenAPI docs are at /css/api/v1/docs.
"""

import json
from datetime import datetime
from typing import Any

from django.db.models import Count, Prefetch, Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Field, NinjaAPI, Schema, Status
from ninja.pagination import paginate

from clinvar_submission_service.api.auth import ApiKeyAuth
from clinvar_submission_service.content import Affiliation, RecordRequest
from clinvar_submission_service.models import ApiKey, Batch, BatchRecord, Record
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


def _affiliation_of(obj: Record | Batch) -> Affiliation | None:
    """Returns a record's or batch's affiliation, or None if it has none."""
    if obj.affiliation_id is None:
        return None
    return Affiliation(id=obj.affiliation_id, name=obj.affiliation_name)


class BatchSummary(Schema):
    """A batch's status at ClinVar and when it changed.

    `status_label` and `status_description` are the words the CSS's pages use, so
    client tools can describe a status the same way.
    """

    slug: str
    status: str
    status_label: str = Field(alias="get_status_display")
    status_description: str = Field(alias="status_help")
    clinvar_submission_id: str
    clinvar_error_code: int | None
    made_at: datetime = Field(alias="added_at")
    sent_at: datetime | None = Field(
        description="When ClinVar accepted the batch, or null if it hasn't yet."
    )
    clinvar_updated_at: datetime | None
    last_checked_at: datetime | None = Field(alias="last_polled_at")


class Attempt(Schema):
    """One try at sending a record to ClinVar, in one batch, and ClinVar's result."""

    batch: BatchSummary
    result: str
    scv: str
    errors: Any = Field(description="ClinVar's errors for the record, as it sent them.")
    added_at: datetime


class RecordSummary(Schema):
    """A record's status and the fields that identify it."""

    slug: str
    affiliation: Affiliation | None
    status: str
    status_label: str = Field(alias="get_status_display")
    status_description: str = Field(alias="status_help")
    tool_id: str
    clinvar_accession: str
    added_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_affiliation(record: Record) -> Affiliation | None:
        """Returns the record's affiliation, if it has one."""
        return _affiliation_of(record)


class RecordDetail(RecordSummary):
    """A record's status, its batches, and its ClinVar JSON as the client sent it."""

    current_batch: str | None = Field(
        description="The slug of the batch the record is in, or null if it's in none."
    )
    attempts: list[Attempt] = Field(
        description="Each batch the record was sent in, oldest first."
    )
    record: dict[str, Any] = Field(alias="payload")

    @staticmethod
    def resolve_attempts(record: Record) -> list[BatchRecord]:
        """Returns the record's attempts, oldest first."""
        return list(record.batch_records.all())  # type: ignore

    @staticmethod
    def resolve_current_batch(record: Record) -> str | None:
        """Returns the slug of the record's batch, if it's in one."""
        if record.status != Record.Status.IN_BATCH:
            return None
        attempts = list(record.batch_records.all())  # type: ignore
        return attempts[-1].batch.slug if attempts else None


def _with_attempts(records: QuerySet[Record]) -> QuerySet[Record]:
    """Returns the records with their attempts and batches, oldest attempt first."""
    attempts = BatchRecord.objects.select_related("batch").order_by("added_at")
    return records.prefetch_related(Prefetch("batch_records", queryset=attempts))


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
def list_records(
    request: HttpRequest,
    status: Record.Status | None = None,
    affiliation: int | None = None,
    updated_since: datetime | None = None,
) -> QuerySet[Record]:
    """Lists the calling client's records, newest first.

    Filter by status, such as waiting_for_batch, or by affiliation, by its AS ID. To
    poll for changes, pass updated_since, the time of the last poll: it matches a
    record that changed at or after that time, or whose batch did, such as when
    ClinVar's status for the batch changed.

    Returns:
        The client's records, a page at a time.
    """
    records = Record.objects.filter(api_key=request.auth)  # ty: ignore[unresolved-attribute] (Ninja sets request.auth.)
    if status:
        records = records.filter(status=status)
    if affiliation is not None:
        records = records.filter(affiliation_id=affiliation)
    if updated_since is not None:
        changed = Q(updated_at__gte=updated_since) | Q(
            batch_records__batch__updated_at__gte=updated_since
        )
        records = records.filter(changed).distinct()
    return records.order_by("-added_at")


@api.get("/records/{slug}", response=RecordDetail)
def read_record(request: HttpRequest, slug: str) -> Record:
    """Reads one of the calling client's records.

    Returns:
        The record, or 404 if the client has none with that slug.
    """
    return get_object_or_404(
        _with_attempts(Record.objects.all()),
        slug=slug,
        api_key=request.auth,  # ty: ignore[unresolved-attribute] (Ninja sets request.auth.)
    )


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


class BatchRecordOut(Schema):
    """One of the client's records in a batch, and ClinVar's result for it."""

    slug: str
    tool_id: str
    position: int
    result: str
    scv: str
    errors: Any = Field(description="ClinVar's errors for the record, as it sent them.")

    @staticmethod
    def resolve_slug(attempt: BatchRecord) -> str:
        """Returns the record's slug."""
        return attempt.record.slug

    @staticmethod
    def resolve_tool_id(attempt: BatchRecord) -> str:
        """Returns the record's tool ID."""
        return attempt.record.tool_id


class BatchOut(BatchSummary):
    """A batch that holds some of the client's records."""

    affiliation: Affiliation | None
    record_count: int = Field(
        alias="client_record_count",
        description="How many of the client's records the batch holds.",
    )

    @staticmethod
    def resolve_affiliation(batch: Batch) -> Affiliation | None:
        """Returns the batch's affiliation, if it has one."""
        return _affiliation_of(batch)


class BatchDetail(BatchOut):
    """A batch and the client's records in it, in batch order."""

    records: list[BatchRecordOut] = Field(alias="client_records")


def _client_batches(api_key: ApiKey) -> QuerySet[Batch]:
    """Returns the batches holding the client's records, newest first.

    Each batch counts and prefetches only the client's records, so a client never
    sees another client's records in a batch they share.
    """
    mine = Q(batch_records__record__api_key=api_key)
    client_records = (
        BatchRecord.objects.filter(record__api_key=api_key)
        .select_related("record")
        .order_by("position")
    )
    return (
        Batch.objects.filter(mine)
        .annotate(client_record_count=Count("batch_records", filter=mine))
        .prefetch_related(
            Prefetch("batch_records", queryset=client_records, to_attr="client_records")
        )
        .order_by("-added_at")
    )


@api.get("/batches", response=list[BatchOut])
@paginate
def list_batches(
    request: HttpRequest,
    status: Batch.Status | None = None,
    affiliation: int | None = None,
) -> QuerySet[Batch]:
    """Lists the batches that hold the calling client's records, newest first.

    Filter by status, such as submitted_to_clinvar, or by affiliation, by its AS ID.

    Returns:
        The batches, a page at a time.
    """
    batches = _client_batches(request.auth)  # ty: ignore[unresolved-attribute] (Ninja sets request.auth.)
    if status:
        batches = batches.filter(status=status)
    if affiliation is not None:
        batches = batches.filter(affiliation_id=affiliation)
    return batches


@api.get("/batches/{slug}", response=BatchDetail)
def read_batch(request: HttpRequest, slug: str) -> Batch:
    """Reads a batch that holds the calling client's records.

    It lists only the client's records in the batch, with ClinVar's result for each.

    Returns:
        The batch, or 404 if it holds none of the client's records.
    """
    return get_object_or_404(_client_batches(request.auth), slug=slug)  # ty: ignore[unresolved-attribute] (Ninja sets request.auth.)
