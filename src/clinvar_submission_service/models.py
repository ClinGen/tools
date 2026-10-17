"""Houses database models for the clinvar_submission_service app."""

from typing import ClassVar

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from common.models import SlugModel


class SubmissionManager(models.Manager["Submission"]):
    def due_to_poll(self) -> models.QuerySet["Submission"]:
        """Returns the pollable submissions whose next poll time has passed."""
        return self.filter(
            status__in=Submission.POLLABLE_STATUSES,
            next_poll_at__lte=timezone.now(),
        )


class Submission(SlugModel):
    """One request to ClinVar, from receipt to a final ClinVar status.

    It's saved before it's forwarded to ClinVar, so there's a record of every request,
    even one ClinVar never got. Its slug is S and the start of its UUID, such as
    S3f2a9c1e.
    """

    slug_prefix = "S"

    class Status(models.TextChoices):
        RECEIVED = "received", "Received"
        SEND_FAILED = "send_failed", "Send Failed"
        SUBMITTED = "submitted", "Submitted"
        PROCESSING = "processing", "Processing"
        PROCESSED = "processed", "Processed"
        ERROR = "error", "Error"

    # The statuses the poller checks on. A received submission hasn't been sent yet,
    # and a send_failed one has no ClinVar ID to poll; the rest are final.
    POLLABLE_STATUSES: ClassVar[list[str]] = [Status.SUBMITTED, Status.PROCESSING]

    payload = models.JSONField(
        verbose_name="Payload",
        help_text="The request body as the client sent it.",
    )
    clinvar_submission_id = models.CharField(
        blank=True,
        default="",
        max_length=32,  # A ClinVar submission ID is of the form SUB1234567.
        verbose_name="ClinVar Submission ID",
        help_text=(
            "The ID ClinVar returned, e.g., SUB999999. Blank until ClinVar accepts "
            "the submission."
        ),
    )
    status = models.CharField(
        choices=Status.choices,
        default=Status.RECEIVED,
        max_length=16,
        verbose_name="Status",
        help_text="Where the submission is between receipt and a final ClinVar status.",
    )
    clinvar_updated_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="ClinVar Updated At",
        help_text="When ClinVar last updated the submission's status.",
    )
    clinvar_error_code = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        verbose_name="ClinVar Error Code",
        help_text=(
            "ClinVar's error code: 1 means some records failed, and 2 means every "
            "record failed."
        ),
    )
    latest_response = models.JSONField(
        blank=True,
        null=True,
        verbose_name="Latest Response",
        help_text="ClinVar's most recent response for the submission.",
    )
    summary_report = models.JSONField(
        blank=True,
        null=True,
        verbose_name="Summary Report",
        help_text="ClinVar's summary report. Empty until processing finishes.",
    )
    error_message = models.TextField(
        blank=True,
        default="",
        verbose_name="Error Message",
        help_text="What went wrong, if anything.",
    )
    added_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Added At",
        help_text="When the submission was received.",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
        help_text="When the submission was last updated.",
    )
    last_polled_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Last Polled At",
        help_text="When the poller last checked ClinVar for this submission.",
    )
    next_poll_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Next Poll At",
        help_text="When the poller should next check ClinVar for this submission.",
    )
    history = HistoricalRecords()

    objects: ClassVar[SubmissionManager] = SubmissionManager()

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        db_table = "submission"
        ordering = ["-added_at"]
        verbose_name = "Submission"
        verbose_name_plural = "Submissions"

    def __str__(self) -> str:
        """Returns the submission's human-readable ID."""
        return self.slug
