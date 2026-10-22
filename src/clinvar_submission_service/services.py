"""Saves submissions, forwards them to ClinVar, and records what happened.

The API and the staff Resend button both forward submissions through here, so a
submission ends up in the same state whichever one sent it.
"""

import logging
from datetime import timedelta
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.utils import timezone
from simple_history.utils import bulk_create_with_history

from clinvar_submission_service.clients import ClinVarClient, ClinVarError
from clinvar_submission_service.content import (
    Affiliation,
    Content,
    record_fields,
    submission_fields,
)
from clinvar_submission_service.models import ApiKey, Record, Submission

logger = logging.getLogger(__name__)

# ClinVar takes at least minutes to start processing a submission, so the poller's first
# check waits this long.
FIRST_POLL_DELAY = timedelta(minutes=5)


def save_submission(
    *, api_key: ApiKey | None, affiliation: Affiliation, payload: dict[str, Any]
) -> Submission:
    """Saves a submission not yet sent to ClinVar, and a Record for each of its records.

    Args:
        api_key: The key of the client that sent it.
        affiliation: The curation group whose classifications it holds.
        payload: The ClinVar content as the client sent it.

    Returns:
        The submission, not yet sent to ClinVar.
    """
    content = Content.model_validate(payload)
    with transaction.atomic():
        submission = Submission.objects.create(
            api_key=api_key,
            affiliation_id=affiliation.id,
            affiliation_name=affiliation.name,
            payload=payload,
            **submission_fields(content),
        )
        # Each record keeps its own JSON, so it can be sent again in another batch.
        records = [
            Record(
                submission=submission,
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
    return submission


def forward_submission(submission: Submission) -> Submission:
    """Sends a submission to ClinVar once and saves the result.

    If ClinVar accepts it, the submission is submitted_to_clinvar, with its ClinVar ID
    and a time for the poller's first check. Otherwise it's send_to_clinvar_failed,
    with the error. It's
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
        submission.status = Submission.Status.SEND_TO_CLINVAR_FAILED
        submission.error_message = str(error)
    else:
        logger.info("Sent %s to ClinVar as %s.", submission.slug, clinvar_id)
        submission.status = Submission.Status.SUBMITTED_TO_CLINVAR
        submission.clinvar_submission_id = clinvar_id or ""
        submission.error_message = ""
        submission.next_poll_at = timezone.now() + FIRST_POLL_DELAY
    submission.save()
    return submission
