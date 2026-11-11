"""Polls ClinVar for the status of each batch that's due.

`Poller.run_pass()` checks one batch of due batches. The poll_clinvar command runs
passes in a loop. Each batch's next poll time is in the database, so stopping and
starting the poller loses nothing.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Protocol

import sentry_sdk
from django.conf import settings
from django.utils import timezone

from clinvar_submission_service.clients import (
    ClinVarClient,
    ClinVarError,
    ClinVarStatus,
)
from clinvar_submission_service.models import Batch
from clinvar_submission_service.services import save_results

logger = logging.getLogger(__name__)

# ClinVar's statuses, and ours for each.
STATUSES = {
    "submitted": Batch.Status.SUBMITTED_TO_CLINVAR,
    "processing": Batch.Status.PROCESSING_AT_CLINVAR,
    "processed": Batch.Status.PROCESSED_BY_CLINVAR,
    "error": Batch.Status.ERROR_AT_CLINVAR,
}

FINAL_STATUSES = {
    Batch.Status.PROCESSED_BY_CLINVAR,
    Batch.Status.ERROR_AT_CLINVAR,
}


class StatusReader(Protocol):
    """The ClinVar calls the poller makes, which ClinVarClient and its fake have."""

    def get_status(self, clinvar_id: str) -> ClinVarStatus:
        """Reads a batch's status from ClinVar."""
        ...

    def get_summary_report(self, url: str) -> dict[str, Any]:
        """Downloads a batch's summary report from ClinVar."""
        ...


def next_delay(
    last_polled_at: datetime | None, now: datetime, retry_after: int | None = None
) -> timedelta:
    """Returns how long to wait before polling a batch again.

    The wait doubles each time, from CSS_POLL_MIN_DELAY up to CSS_POLL_MAX_DELAY, and
    is at least as long as ClinVar's Retry-After.

    Args:
        last_polled_at: When the batch was last polled, if ever.
        now: The time of this poll.
        retry_after: How many seconds ClinVar asked us to wait, if it did.
    """
    delay = settings.CSS_POLL_MIN_DELAY
    if last_polled_at:
        delay = max(delay, 2 * (now - last_polled_at))
    delay = min(delay, settings.CSS_POLL_MAX_DELAY)
    if retry_after:
        delay = max(delay, timedelta(seconds=retry_after))
    return delay


class Poller:
    """Polls ClinVar for due batches, one batch per pass."""

    def __init__(self, client: StatusReader | None = None) -> None:
        """Stores the client to poll with, or builds one from settings when needed."""
        self._client = client
        self.stopping = False

    def stop(self) -> None:
        """Asks the poller to stop once it finishes the current batch."""
        self.stopping = True

    def run_pass(self) -> int:
        """Polls up to CSS_POLLS_PER_PASS of the batches that are due.

        Returns:
            How many batches were polled.
        """
        due = list(Batch.objects.due_to_poll()[: settings.CSS_POLLS_PER_PASS])
        if not due:
            return 0
        if not self._client:
            self._client = ClinVarClient.from_settings()
        polled = 0
        for batch in due:
            if self.stopping:
                break
            self._poll(self._client, batch)
            polled += 1
        return polled

    def _poll(self, client: StatusReader, batch: Batch) -> None:
        """Polls one batch and saves what ClinVar said."""
        now = timezone.now()
        last_polled_at = batch.last_polled_at
        retry_after = None
        try:
            status = client.get_status(batch.clinvar_submission_id)
            done = self._record(client, batch, status)
        except Exception as error:
            # One batch's failure, even an unexpected one, mustn't stop the rest.
            logger.warning("Couldn't poll %s: %s", batch.slug, error)
            sentry_sdk.capture_exception(error)
            if isinstance(error, ClinVarError):
                retry_after = error.retry_after
            done = False
        batch.last_polled_at = now
        batch.next_poll_at = (
            None if done else now + next_delay(last_polled_at, now, retry_after)
        )
        batch.save()

    def _record(
        self, client: StatusReader, batch: Batch, status: ClinVarStatus
    ) -> bool:
        """Saves ClinVar's status on a batch, without saving the batch.

        If a final status's summary report can't be downloaded, the client's error
        propagates and the status stays as it was, so the next poll tries again.

        Returns:
            Whether the batch has reached a final status.
        """
        batch.latest_response = status.response
        batch.clinvar_updated_at = status.updated_at
        batch.clinvar_error_code = status.error_code
        new_status = STATUSES.get(status.status)
        if new_status is None:
            logger.warning(
                "ClinVar gave %s an unknown status: %s", batch.slug, status.status
            )
            return False
        if new_status in FINAL_STATUSES and status.summary_report_url:
            batch.summary_report = client.get_summary_report(status.summary_report_url)
            save_results(batch)
        batch.status = new_status
        logger.info("%s is %s.", batch.slug, new_status)
        return new_status in FINAL_STATUSES
