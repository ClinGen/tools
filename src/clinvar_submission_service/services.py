"""Saves records and batches, forwards batches to ClinVar, and records what happened.

The API saves records through here, and the staff pages forward batches through here.
"""

import logging
from datetime import timedelta
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from simple_history.utils import bulk_create_with_history, update_change_reason

from clinvar_submission_service.clients import ClinVarClient, ClinVarError
from clinvar_submission_service.content import (
    Affiliation,
    Content,
    GermlineRecord,
    batch_fields,
    fields_of,
    record_fields,
)
from clinvar_submission_service.models import ApiKey, Batch, BatchRecord, Record

logger = logging.getLogger(__name__)

# ClinVar takes at least minutes to start processing a batch, so the poller's first
# check waits this long.
FIRST_POLL_DELAY = timedelta(minutes=5)


def save_record(
    *, api_key: ApiKey | None, affiliation: Affiliation, payload: dict[str, Any]
) -> tuple[Record, bool]:
    """Saves a record to wait for a batch.

    If the affiliation has a waiting record with the same local ID, that record is
    replaced, and its history keeps the old version. Otherwise a new record is made.

    Args:
        api_key: The key of the client that sent it.
        affiliation: The curation group whose classification it is.
        payload: The record's ClinVar JSON as the client sent it.

    Returns:
        The record, and whether it's new.
    """
    fields = fields_of(GermlineRecord.model_validate(payload))
    with transaction.atomic():
        record = None
        if fields["local_id"]:
            record = (
                Record.objects.select_for_update()
                .filter(
                    affiliation_id=affiliation.id,
                    local_id=fields["local_id"],
                    status=Record.Status.WAITING_FOR_BATCH,
                )
                .first()
            )
        created = record is None
        if record is None:
            record = Record(affiliation_id=affiliation.id)
        record.api_key = api_key
        record.affiliation_name = affiliation.name
        record.payload = payload
        for name, value in fields.items():
            setattr(record, name, value)
        record.save()
    return record, created


class NotWithdrawableError(Exception):
    """Raised for a record that's no longer waiting, so it can't be withdrawn."""

    message = "Only a record that's waiting for a batch can be withdrawn."


def withdraw_record(record: Record, *, by: str) -> Record:
    """Withdraws a waiting record, so it won't be sent to ClinVar.

    Args:
        record: The record.
        by: Who withdrew it, such as "staff" or "the GCI", for its history.

    Returns:
        The record, saved.

    Raises:
        NotWithdrawableError: If the record isn't waiting for a batch.
    """
    with transaction.atomic():
        record = Record.objects.select_for_update().get(pk=record.pk)
        if record.status != Record.Status.WAITING_FOR_BATCH:
            raise NotWithdrawableError(NotWithdrawableError.message)
        record.status = Record.Status.WITHDRAWN
        record.save()
        update_change_reason(record, f"Withdrawn by {by}")
    return record


def save_batch(
    *, api_key: ApiKey | None, affiliation: Affiliation, payload: dict[str, Any]
) -> Batch:
    """Saves a batch not yet sent to ClinVar, and a Record for each of its records.

    Args:
        api_key: The key of the client that sent it.
        affiliation: The curation group whose classifications it holds.
        payload: The ClinVar content as the client sent it.

    Returns:
        The batch, not yet sent to ClinVar.
    """
    content = Content.model_validate(payload)
    with transaction.atomic():
        batch = Batch.objects.create(
            api_key=api_key,
            affiliation_id=affiliation.id,
            affiliation_name=affiliation.name,
            **batch_fields(content),
        )
        # Each record keeps its own JSON, so it can be sent again in another batch.
        records = [
            Record(
                api_key=api_key,
                affiliation_id=affiliation.id,
                affiliation_name=affiliation.name,
                payload=item,
                status=Record.Status.IN_BATCH,
                **fields,
            )
            for item, fields in zip(
                payload["germlineSubmission"], record_fields(content), strict=True
            )
        ]
        # bulk_create skips save(), so the slugs and history are added for it.
        Record.set_unique_slugs(records)
        bulk_create_with_history(records, Record)
        attempts = [
            BatchRecord(batch=batch, record=record, position=position)
            for position, record in enumerate(records)
        ]
        bulk_create_with_history(attempts, BatchRecord)
    return batch


def build_payload(batch: Batch) -> dict[str, Any]:
    """Returns the ClinVar content for a batch, built from its records.

    The records' JSON goes in germlineSubmission in the batch's order, followed by the
    batch's submission-level fields, if it has them.

    Returns:
        The content to send to ClinVar.
    """
    attempts = batch.batch_records.select_related("record")  # type: ignore
    payload: dict[str, Any] = {
        "germlineSubmission": [attempt.record.payload for attempt in attempts]
    }
    if batch.assertion_criteria_db:
        payload["assertionCriteria"] = {
            "db": batch.assertion_criteria_db,
            "id": batch.assertion_criteria_id,
        }
    if batch.behalf_org_id:
        payload["behalfOrgID"] = batch.behalf_org_id
    if batch.release_status:
        payload["clinvarSubmissionReleaseStatus"] = batch.release_status
    return payload


def forward_batch(batch: Batch) -> Batch:
    """Sends a batch to ClinVar once and saves the result.

    If ClinVar accepts it, the batch is submitted_to_clinvar, with its ClinVar ID
    and a time for the poller's first check. Otherwise it's send_to_clinvar_failed,
    with the error. It's never retried here; staff resend it from its page.

    Args:
        batch: A saved batch that hasn't reached ClinVar.

    Returns:
        The batch, saved.
    """
    try:
        clinvar_id = ClinVarClient.from_settings().submit(build_payload(batch))
    except (ClinVarError, ImproperlyConfigured) as error:
        logger.warning("Couldn't send %s to ClinVar: %s", batch.slug, error)
        batch.status = Batch.Status.SEND_TO_CLINVAR_FAILED
        batch.error_message = str(error)
    else:
        logger.info("Sent %s to ClinVar as %s.", batch.slug, clinvar_id)
        batch.status = Batch.Status.SUBMITTED_TO_CLINVAR
        batch.clinvar_submission_id = clinvar_id or ""
        batch.error_message = ""
        batch.next_poll_at = timezone.now() + FIRST_POLL_DELAY
    batch.save()
    return batch
