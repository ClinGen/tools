"""Forwards submissions to ClinVar and records what happened.

The API and the staff Resend button both forward submissions through here, so a
submission ends up in the same state whichever one sent it.
"""

import logging
from datetime import timedelta
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from clinvar_submission_service.clients import ClinVarClient, ClinVarError
from clinvar_submission_service.models import Submission

logger = logging.getLogger(__name__)

# ClinVar takes at least minutes to start processing a submission, so the poller's first
# check waits this long.
FIRST_POLL_DELAY = timedelta(minutes=5)

# The most records ClinVar accepts in one submission.
MAX_RECORDS = 10_000


def count_records(content: dict[str, Any]) -> int:
    """Returns how many records a ClinVar submission's content holds.

    Records are the content's submissions plus the accessions it deletes.
    """
    submissions = content.get("clinvarSubmission") or []
    deletions = (content.get("clinvarDeletion") or {}).get("accessionSet") or []
    return len(submissions) + len(deletions)


def forward_submission(submission: Submission) -> Submission:
    """Sends a submission to ClinVar once and saves the result.

    If ClinVar accepts it, the submission is submitted, with its ClinVar ID and a time
    for the poller's first check. Otherwise it's send_failed, with the error. It's
    never retried here; staff resend it from its page.

    Args:
        submission: A saved submission that hasn't reached ClinVar.

    Returns:
        The submission, saved.
    """
    try:
        clinvar_id = ClinVarClient.from_settings().submit(submission.payload)
    except (ClinVarError, ImproperlyConfigured) as error:
        logger.warning("Couldn't send %s to ClinVar: %s", submission.slug, error)
        submission.status = Submission.Status.SEND_FAILED
        submission.error_message = str(error)
    else:
        logger.info("Sent %s to ClinVar as %s.", submission.slug, clinvar_id)
        submission.status = Submission.Status.SUBMITTED
        submission.clinvar_submission_id = clinvar_id or ""
        submission.error_message = ""
        submission.next_poll_at = timezone.now() + FIRST_POLL_DELAY
    submission.save()
    return submission
