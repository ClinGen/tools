"""Saves records and batches, forwards batches to ClinVar, and records what happened.

The API saves and withdraws records through here, and the staff pages withdraw records
and make and send batches through here.
"""

import logging
from collections.abc import Iterable
from typing import Any

from django.conf import settings
from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from simple_history.utils import (
    bulk_create_with_history,
    bulk_update_with_history,
    update_change_reason,
)

from clinvar_submission_service.clients import ClinVarClient, ClinVarError
from clinvar_submission_service.content import (
    MAX_RECORDS,
    Affiliation,
    GermlineRecord,
    fields_of,
)
from clinvar_submission_service.models import (
    AffiliationSettings,
    ApiKey,
    Batch,
    BatchRecord,
    Record,
)

logger = logging.getLogger(__name__)


def save_record(
    *, api_key: ApiKey | None, affiliation: Affiliation, payload: dict[str, Any]
) -> tuple[Record, bool]:
    """Saves a record to wait for a batch.

    If the affiliation has a waiting record with the same tool ID, that record is
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
        if fields["tool_id"]:
            record = (
                Record.objects.select_for_update()
                .filter(
                    affiliation_id=affiliation.id,
                    tool_id=fields["tool_id"],
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


class BatchNotMadeError(Exception):
    """Raised when the chosen records can't make a batch, with a message for staff."""


def check_batchable(records: list[Record]) -> None:
    """Checks that records can make a batch, without making one.

    Raises:
        BatchNotMadeError: If there are no records, more than ClinVar takes in one
            submission, records from more than one affiliation, or records that
            aren't waiting.
    """
    if not records:
        error_message = "Pick at least one record."
        raise BatchNotMadeError(error_message)
    if len(records) > MAX_RECORDS:
        error_message = f"A batch can hold at most {MAX_RECORDS:,} records."
        raise BatchNotMadeError(error_message)
    if len({record.affiliation_id for record in records}) > 1:
        error_message = "A batch can hold only one affiliation's records."
        raise BatchNotMadeError(error_message)
    if any(r.status != Record.Status.WAITING_FOR_BATCH for r in records):
        error_message = "Only records waiting for a batch can be added to one."
        raise BatchNotMadeError(error_message)


def make_batch(records: Iterable[Record], *, made_by: User | None = None) -> Batch:
    """Makes a batch, not yet sent to ClinVar, of one affiliation's waiting records.

    The records go in the batch in the order given and are marked as in a batch, so
    they can't join another one. The batch copies its affiliation's settings, if it
    has any, so it keeps the values it's sent with. If `check_batchable()` refuses
    the records, its BatchNotMadeError passes through and nothing is saved.

    Args:
        records: The records, all waiting and from one affiliation.
        made_by: The staff member making it.

    Returns:
        The batch.
    """
    pks = [record.pk for record in records]
    with transaction.atomic():
        locked = Record.objects.select_for_update().in_bulk(pks)
        chosen = [locked[pk] for pk in pks]
        check_batchable(chosen)
        newest = max(chosen, key=lambda record: record.added_at)
        settings = AffiliationSettings.objects.filter(
            affiliation_id=newest.affiliation_id
        ).first()
        batch = Batch.objects.create(
            made_by=made_by,
            affiliation_id=newest.affiliation_id,
            affiliation_name=newest.affiliation_name,
            **_settings_fields(settings),
        )
        bulk_create_with_history(
            [
                BatchRecord(batch=batch, record=record, position=position)
                for position, record in enumerate(chosen)
            ],
            BatchRecord,
        )
        # A bulk update skips auto_now, so set updated_at here; clients poll for it.
        now = timezone.now()
        for record in chosen:
            record.status = Record.Status.IN_BATCH
            record.updated_at = now
        bulk_update_with_history(chosen, Record, ["status", "updated_at"])
    return batch


def _settings_fields(settings: AffiliationSettings | None) -> dict[str, Any]:
    """Returns the Batch fields copied from an affiliation's settings.

    Returns:
        The field values, by name, or {} if the affiliation has no settings.
    """
    if settings is None:
        return {}
    return {
        "assertion_criteria_db": settings.assertion_criteria_db,
        "assertion_criteria_id": settings.assertion_criteria_id,
        "behalf_org_id": settings.behalf_org_id,
        "release_status": settings.release_status,
    }


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


def report_results(report: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Returns each record's result in ClinVar's summary report, by its tool ID.

    Returns:
        The results, by tool ID; {} if there's no report yet.
    """
    results = {}
    for result in (report or {}).get("submissions") or []:
        tool_id = (result.get("identifiers") or {}).get("localID")
        if tool_id:
            results[tool_id] = result
    return results


def save_results(batch: Batch) -> None:
    """Saves each record's result from a batch's summary report.

    A record ClinVar accepted gets its SCV. A record that failed goes back to waiting,
    so it can join a later batch, and its attempt keeps ClinVar's errors. A result
    whose tool ID matches none of the batch's records is logged and skipped.
    """
    results = report_results(batch.summary_report)
    with transaction.atomic():
        attempts = batch.batch_records.select_related("record")  # type: ignore
        for attempt in attempts:
            result = results.pop(attempt.record.tool_id, None)
            if result is not None:
                _save_result(attempt, result)
    for tool_id in results:
        logger.warning(
            "%s's summary report has a result for %s, which isn't in the batch.",
            batch.slug,
            tool_id,
        )


def _save_result(attempt: BatchRecord, result: dict[str, Any]) -> None:
    """Saves one record's result on its attempt and on the record."""
    record = attempt.record
    if result.get("processingStatus") == BatchRecord.Result.SUCCESS:
        scv = (result.get("identifiers") or {}).get("clinvarAccession") or ""
        attempt.result = BatchRecord.Result.SUCCESS
        attempt.scv = scv
        record.status = Record.Status.SUCCEEDED_AT_CLINVAR
        record.clinvar_accession = scv
    else:
        attempt.result = BatchRecord.Result.ERROR
        attempt.errors = result.get("errors")
        record.status = Record.Status.WAITING_FOR_BATCH
    attempt.save()
    record.save()


def forward_batch(batch: Batch) -> Batch:
    """Sends a batch to ClinVar once and saves the result.

    If ClinVar accepts it, the batch is submitted_to_clinvar, with its ClinVar ID,
    when it was sent, and a time for the poller's first check. Otherwise it's
    send_to_clinvar_failed, with the error. It's never retried here; staff resend it
    from its page.

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
        batch.sent_at = timezone.now()
        batch.error_message = ""
        batch.next_poll_at = timezone.now() + settings.CSS_FIRST_POLL_DELAY
    batch.save()
    return batch
