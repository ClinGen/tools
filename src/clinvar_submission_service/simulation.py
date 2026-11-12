"""Stands in for ClinVar when CSS_SIMULATE_CLINVAR is on, so the workflow can be tried.

The web server sends batches and the poller checks on them in separate processes, so
the simulator keeps nothing in memory. It reads what it needs from the database: a
batch by its ClinVar ID, and its records. Each poll moves a batch one step, from
submitted to processing to processed or error, and each record's result comes from a
hash of the ClinVar ID and its local ID, so it's the same every time for that batch.
"""

import hashlib
import random
from typing import Any

from django.db import transaction
from django.utils import timezone
from simple_history.utils import bulk_update_with_history

from clinvar_submission_service.clients import ClinVarError, ClinVarStatus
from clinvar_submission_service.models import Batch, BatchRecord, Record

# How often sending a batch fails, so staff can try Resend.
SEND_FAILURE_RATE = 0.1

# How many records in 100 ClinVar accepts.
SUCCESS_PERCENT = 85

# Where the poller downloads a simulated summary report from.
REPORT_URL_PREFIX = "simulated://"

# What ClinVar might say about a record it didn't accept.
ERROR_MESSAGES = [
    (
        "This record is a duplicate of a record your organization already submitted "
        "for the same variant and condition."
    ),
    "The HGVS expression couldn't be validated against the reference sequence.",
    "The condition ID wasn't found in the database it names.",
    "The clinvarAccession doesn't belong to your organization.",
]


def _digest(*parts: str) -> int:
    """Returns a stable number for the parts, the same in every process."""
    return int(hashlib.sha256(":".join(parts).encode()).hexdigest(), 16)


def _succeeds(clinvar_id: str, record: Record) -> bool:
    """Returns whether ClinVar accepts the record in the simulated batch."""
    return _digest(clinvar_id, record.local_id) % 100 < SUCCESS_PERCENT


class SimulatedClinVarClient:
    """Has ClinVarClient's methods, but answers as ClinVar might, without a request."""

    def submit(self, content: dict[str, Any], *, dry_run: bool = False) -> str | None:  # ruff: ignore[unused-method-argument] (ClinVarClient's signature.)
        """Accepts a batch, or sometimes fails as if ClinVar couldn't be reached.

        Returns:
            A new ClinVar ID, or None for a dry run.

        Raises:
            ClinVarError: About one time in ten, as a retryable failure.
        """
        if dry_run:
            return None
        if random.random() < SEND_FAILURE_RATE:  # ruff: ignore[suspicious-non-cryptographic-random-usage] (Not a secret.)
            error_message = "Simulated ClinVar returned 503: try again later."
            raise ClinVarError(error_message, retryable=True)
        return f"SUB{random.randrange(10**7):07d}"  # ruff: ignore[suspicious-non-cryptographic-random-usage] (Not a secret.)

    def get_status(self, clinvar_id: str) -> ClinVarStatus:
        """Returns the step after the batch's current status.

        Returns:
            Processing for a submitted batch, and otherwise processed or error, with
            a summary report URL and, for error, ClinVar's error code.
        """
        batch = Batch.objects.get(clinvar_submission_id=clinvar_id)
        if batch.status == Batch.Status.SUBMITTED_TO_CLINVAR:
            status, error_code, report_url = "processing", None, ""
        else:
            accepted = [_succeeds(clinvar_id, record) for record in _records(batch)]
            report_url = REPORT_URL_PREFIX + clinvar_id
            if all(accepted):
                status, error_code = "processed", None
            else:
                status, error_code = "error", 1 if any(accepted) else 2
        return ClinVarStatus(
            status=status,
            updated_at=timezone.now(),
            error_code=error_code,
            summary_report_url=report_url,
            response={
                "actions": [{"id": f"{clinvar_id}-1", "status": status}],
                "simulated": True,
            },
        )

    def get_summary_report(self, url: str) -> dict[str, Any]:
        """Returns a summary report in ClinVar's shape for the batch at the URL.

        Returns:
            The report, with one result per record, in the batch's order.
        """
        clinvar_id = url.removeprefix(REPORT_URL_PREFIX)
        batch = Batch.objects.get(clinvar_submission_id=clinvar_id)
        results = [_result(clinvar_id, record) for record in _records(batch)]
        successes = sum(r["processingStatus"] == "Success" for r in results)
        return {
            "submissionName": "",
            "totalCount": len(results),
            "totalErrors": len(results) - successes,
            "totalSuccess": successes,
            "totalPublic": 0,
            "submissions": results,
        }


def _records(batch: Batch) -> list[Record]:
    """Returns the batch's records, in its order."""
    attempts = batch.batch_records.select_related("record")  # type: ignore
    return [attempt.record for attempt in attempts]


def _result(clinvar_id: str, record: Record) -> dict[str, Any]:
    """Returns ClinVar's result for one record, in its summary report's shape."""
    identifiers: dict[str, str] = {"localID": record.local_id}
    if _succeeds(clinvar_id, record):
        scv = record.clinvar_accession or (
            f"SCV{_digest(clinvar_id, record.local_id, 'scv') % 10**9:09d}"
        )
        return {
            "identifiers": identifiers | {"clinvarAccession": scv},
            "processingStatus": "Success",
        }
    message = ERROR_MESSAGES[_digest(clinvar_id, record.local_id) % len(ERROR_MESSAGES)]
    return {
        "identifiers": identifiers,
        "processingStatus": "Error",
        "errors": [{"output": {"errors": [{"userMessage": message}]}}],
    }


@transaction.atomic
def delete_all_batches() -> int:
    """Deletes every batch, so the simulated workflow can start over.

    Records that were in a batch go back to waiting. Succeeded and withdrawn records
    stay as they are.

    Returns:
        How many batches were deleted.
    """
    count = Batch.objects.count()
    BatchRecord.objects.all().delete()
    Batch.objects.all().delete()
    in_batch = list(Record.objects.filter(status=Record.Status.IN_BATCH))
    for record in in_batch:
        record.status = Record.Status.WAITING_FOR_BATCH
    bulk_update_with_history(
        in_batch, Record, ["status"], default_change_reason="Its batch was deleted."
    )
    return count


@transaction.atomic
def delete_all_records() -> int:
    """Deletes every record and, since a batch is made of records, every batch.

    Returns:
        How many records were deleted.
    """
    count = Record.objects.count()
    BatchRecord.objects.all().delete()
    Batch.objects.all().delete()
    Record.objects.all().delete()
    return count
