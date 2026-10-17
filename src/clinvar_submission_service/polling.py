"""Polls ClinVar for the status of each submission that's due.

`Poller.run_pass()` checks one batch of due submissions. The poll_clinvar command runs
passes in a loop. Each submission's next poll time is in the database, so stopping and
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
from clinvar_submission_service.models import Submission

logger = logging.getLogger(__name__)

# ClinVar's statuses, and ours for each.
STATUSES = {
    "submitted": Submission.Status.SUBMITTED,
    "processing": Submission.Status.PROCESSING,
    "processed": Submission.Status.PROCESSED,
    "error": Submission.Status.ERROR,
}

FINAL_STATUSES = {Submission.Status.PROCESSED, Submission.Status.ERROR}


class StatusReader(Protocol):
    """The ClinVar calls the poller makes, which ClinVarClient and its fake have."""

    def get_status(self, clinvar_id: str) -> ClinVarStatus:
        """Reads a submission's status from ClinVar."""
        ...

    def get_summary_report(self, url: str) -> dict[str, Any]:
        """Downloads a submission's summary report from ClinVar."""
        ...


def next_delay(
    last_polled_at: datetime | None, now: datetime, retry_after: int | None = None
) -> timedelta:
    """Returns how long to wait before polling a submission again.

    The wait doubles each time, from CSS_POLL_MIN_DELAY up to CSS_POLL_MAX_DELAY, and
    is at least as long as ClinVar's Retry-After.

    Args:
        last_polled_at: When the submission was last polled, if ever.
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
    """Polls ClinVar for due submissions, one batch per pass."""

    def __init__(self, client: StatusReader | None = None) -> None:
        """Stores the client to poll with, or builds one from settings when needed."""
        self._client = client
        self.stopping = False

    def stop(self) -> None:
        """Asks the poller to stop once it finishes the current submission."""
        self.stopping = True

    def run_pass(self) -> int:
        """Polls one batch of the submissions that are due.

        Returns:
            How many submissions were polled.
        """
        batch = list(Submission.objects.due_to_poll()[: settings.CSS_POLL_BATCH_SIZE])
        if not batch:
            return 0
        if not self._client:
            self._client = ClinVarClient.from_settings()
        polled = 0
        for submission in batch:
            if self.stopping:
                break
            self._poll(self._client, submission)
            polled += 1
        return polled

    def _poll(self, client: StatusReader, submission: Submission) -> None:
        """Polls one submission and saves what ClinVar said."""
        now = timezone.now()
        last_polled_at = submission.last_polled_at
        retry_after = None
        try:
            status = client.get_status(submission.clinvar_submission_id)
            done = self._record(client, submission, status)
        except Exception as error:
            # One submission's failure, even an unexpected one, mustn't stop the rest.
            logger.warning("Couldn't poll %s: %s", submission.slug, error)
            sentry_sdk.capture_exception(error)
            if isinstance(error, ClinVarError):
                retry_after = error.retry_after
            done = False
        submission.last_polled_at = now
        submission.next_poll_at = (
            None if done else now + next_delay(last_polled_at, now, retry_after)
        )
        submission.save()

    def _record(
        self, client: StatusReader, submission: Submission, status: ClinVarStatus
    ) -> bool:
        """Saves ClinVar's status on a submission, without saving the submission.

        If a final status's summary report can't be downloaded, the client's error
        propagates and the status stays as it was, so the next poll tries again.

        Returns:
            Whether the submission has reached a final status.
        """
        submission.latest_response = status.response
        submission.clinvar_updated_at = status.updated_at
        submission.clinvar_error_code = status.error_code
        new_status = STATUSES.get(status.status)
        if new_status is None:
            logger.warning(
                "ClinVar gave %s an unknown status: %s", submission.slug, status.status
            )
            return False
        if new_status in FINAL_STATUSES and status.summary_report_url:
            submission.summary_report = client.get_summary_report(
                status.summary_report_url
            )
        submission.status = new_status
        logger.info("%s is %s.", submission.slug, new_status)
        return new_status in FINAL_STATUSES
