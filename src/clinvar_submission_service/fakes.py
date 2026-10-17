"""Stands in for ClinVar in tests, so they never send a request."""

from datetime import UTC, datetime
from typing import Any

from clinvar_submission_service.clients import ClinVarError, ClinVarStatus


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
