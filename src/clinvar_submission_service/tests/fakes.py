"""Stands in for ClinVar in tests, so they never send a request.

Also builds sample ClinVar content for tests and fixtures.
"""

from datetime import UTC, datetime
from typing import Any

from clinvar_submission_service.clients import ClinVarError, ClinVarStatus
from clinvar_submission_service.models import (
    AffectedStatus,
    AlleleOrigin,
    Assembly,
    Batch,
    BatchRecord,
    Classification,
    CollectionMethod,
    ConditionDb,
    Record,
    RecordStatus,
)


class FakeClinVarClient:
    """Holds ClinVar's submissions in memory, with the same methods as ClinVarClient.

    Set `submit_error`, `status_error`, or `report_error` to a ClinVarError to make the
    matching call raise it. Set a submission's status with `set_status()`.
    """

    def __init__(self) -> None:
        """Starts with no submissions."""
        self.submitted: list[dict[str, Any]] = []
        self.statuses: dict[str, ClinVarStatus] = {}
        self.reports: dict[str, dict[str, Any]] = {}
        self.submit_error: ClinVarError | None = None
        self.status_error: ClinVarError | None = None
        self.report_error: ClinVarError | None = None

    def submit(self, content: dict[str, Any], *, dry_run: bool = False) -> str | None:
        """Records the content.

        Returns:
            The next ClinVar ID, or None for a dry run.
        """
        if self.submit_error:
            raise self.submit_error
        if dry_run:
            return None
        self.submitted.append(content)
        clinvar_id = f"SUB{len(self.submitted):06d}"
        self.set_status(clinvar_id, "submitted")
        return clinvar_id

    def set_status(
        self,
        clinvar_id: str,
        status: str,
        *,
        error_code: int | None = None,
        report: dict[str, Any] | None = None,
    ) -> None:
        """Sets the status ClinVar reports for a submission, and its summary report."""
        report_url = (
            f"https://clinvar.example.org/{clinvar_id}-report.json" if report else ""
        )
        if report is not None:
            self.reports[report_url] = report
        self.statuses[clinvar_id] = ClinVarStatus(
            status=status,
            updated_at=datetime.now(UTC),
            error_code=error_code,
            summary_report_url=report_url,
            response={"actions": [{"id": f"{clinvar_id}-1", "status": status}]},
        )

    def get_status(self, clinvar_id: str) -> ClinVarStatus:
        """Returns the status set for a submission."""
        if self.status_error:
            raise self.status_error
        return self.statuses[clinvar_id]

    def get_summary_report(self, url: str) -> dict[str, Any]:
        """Returns the report set for a URL."""
        if self.report_error:
            raise self.report_error
        return self.reports[url]


def make_record(local_id: str = "var-1", **fields: object) -> dict[str, Any]:
    """Returns a germline record, likely pathogenic for an example condition.

    Args:
        local_id: The record's localID.
        **fields: Fields to set in place of the defaults, by ClinVar's names.

    Returns:
        The record, as the client would send it.
    """
    record = {
        "recordStatus": "novel",
        "localID": local_id,
        "localKey": local_id,
        "submittedAssembly": "GRCh38",
        "variantSet": {
            "variant": [
                {"hgvs": "NC_000017.11:g.43045712T>C", "gene": [{"symbol": "BRCA1"}]}
            ]
        },
        "conditionSet": {"condition": [{"db": "MONDO", "id": "MONDO:0011450"}]},
        "germlineClassification": {
            "germlineClassificationDescription": "Likely pathogenic",
            "modeOfInheritance": "Autosomal dominant inheritance",
            "dateLastEvaluated": "2026-10-01",
            "comment": "Criteria met: PM2, PS3, PP3.",
        },
        "observedIn": [
            {
                "alleleOrigin": "germline",
                "affectedStatus": "not provided",
                "collectionMethod": "curation",
            }
        ],
    }
    return record | fields


def make_content(*records: dict[str, Any]) -> dict[str, Any]:
    """Returns ClinVar content with the given records, or one sample record.

    Returns:
        The content, as the client would send it.
    """
    return {
        "germlineSubmission": list(records) or [make_record()],
        "assertionCriteria": {"db": "PubMed", "id": "25741868"},
    }


def make_saved_record(batch: Batch | None, local_id: str, **fields: object) -> Record:
    """Saves and returns a likely pathogenic record.

    Args:
        batch: The batch to add the record to, or None for a record in no batch.
        local_id: The record's local ID.
        **fields: Fields to set in place of the defaults.

    Returns:
        The saved record.
    """
    defaults = {
        "record_status": RecordStatus.NOVEL,
        "local_id": local_id,
        "submitted_assembly": Assembly.GRCH38,
        "hgvs": "NC_000017.11:g.43045712T>C",
        "condition_db": ConditionDb.MONDO,
        "condition_id": "MONDO:0011450",
        "classification": Classification.LIKELY_PATHOGENIC,
        "allele_origin": AlleleOrigin.GERMLINE,
        "affected_status": AffectedStatus.NOT_PROVIDED,
        "collection_method": CollectionMethod.CURATION,
    }
    record = Record.objects.create(**(defaults | fields))
    if batch:
        BatchRecord.objects.create(
            batch=batch,
            record=record,
            position=batch.batch_records.count(),  # type: ignore
        )
    return record
