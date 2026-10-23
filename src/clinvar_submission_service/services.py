"""Saves batches, forwards them to ClinVar, and records what happened.

The API and the staff Resend button both forward batches through here, so a
batch ends up in the same state whichever one sent it.
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
    batch_fields,
    record_fields,
)
from clinvar_submission_service.models import ApiKey, Batch, Record

logger = logging.getLogger(__name__)

# ClinVar takes at least minutes to start processing a batch, so the poller's first
# check waits this long.
FIRST_POLL_DELAY = timedelta(minutes=5)


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
            payload=payload,
            **batch_fields(content),
        )
        # Each record keeps its own JSON, so it can be sent again in another batch.
        records = [
            Record(
                batch=batch,
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
    return batch


def forward_batch(batch: Batch) -> Batch:
    """Sends a batch to ClinVar once and saves the result.

    If ClinVar accepts it, the batch is submitted_to_clinvar, with its ClinVar ID
    and a time for the poller's first check. Otherwise it's send_to_clinvar_failed,
    with the error. It's
    never retried here; staff resend it from its page.

    Args:
        batch: A saved batch that hasn't reached ClinVar.

    Returns:
        The batch, saved.
    """
    try:
        clinvar_id = ClinVarClient.from_settings().submit(batch.payload)
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
