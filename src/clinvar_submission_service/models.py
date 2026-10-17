"""Houses database models for the clinvar_submission_service app."""

import hashlib
import secrets
from typing import ClassVar

from django.db import models
from django.utils import timezone
from simple_history.models import HistoricalRecords

from common.models import SlugModel, UUIDModel


class SubmissionManager(models.Manager["Submission"]):
    def due_to_poll(self) -> models.QuerySet["Submission"]:
        """Returns the pollable submissions whose next poll time has passed.

        The ones that have waited longest come first.
        """
        return self.filter(
            status__in=Submission.POLLABLE_STATUSES,
            next_poll_at__lte=timezone.now(),
        ).order_by("next_poll_at")


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

    api_key = models.ForeignKey(
        "ApiKey",
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="submissions",
        verbose_name="Client",
        help_text="The API key of the client that sent the submission.",
    )
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


def _hash(raw_key: str) -> str:
    """Returns the hash of an API key that's stored in place of the key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


class ApiKeyManager(models.Manager["ApiKey"]):
    def create_key(self, *, name: str) -> tuple["ApiKey", str]:
        """Creates an API key for a client.

        Args:
            name: The client's name, such as "GCI".

        Returns:
            The new key and its raw value, which is never stored or shown again.
        """
        api_key = self.model(name=name)
        raw_key = api_key.set_new_key()
        api_key.save()
        return api_key, raw_key

    def verify(self, raw_key: str) -> "ApiKey | None":
        """Returns the active key with this raw value, and records its use.

        Returns:
            The key, or None if no active key matches.
        """
        if not raw_key:
            return None
        api_key = self.filter(key_hash=_hash(raw_key), is_active=True).first()
        if api_key:
            # update() skips the history, which shouldn't get a row per request.
            now = timezone.now()
            self.filter(pk=api_key.pk).update(last_used_at=now)
            api_key.last_used_at = now
        return api_key


# Every raw key starts with this, so a leaked one is easy to recognize.
API_KEY_PREFIX = "css_"

# How much of a raw key is kept, so staff can tell keys apart.
PREFIX_LENGTH = 8


class ApiKey(UUIDModel):
    """The key one client system sends to use the CSS's API.

    Only a hash of the key is stored. Staff create keys in the Django admin, which shows
    the raw key once.
    """

    name = models.CharField(
        max_length=128,
        verbose_name="Client",
        help_text="The client system that uses this key, such as the GCI.",
    )
    prefix = models.CharField(
        editable=False,
        max_length=PREFIX_LENGTH,
        verbose_name="Prefix",
        help_text="The start of the key, so you can tell keys apart.",
    )
    key_hash = models.CharField(
        editable=False,
        max_length=64,
        unique=True,
        verbose_name="Key Hash",
        help_text="The SHA-256 hash of the key. The key itself isn't stored.",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Active",
        help_text="Whether the key can call the API. Turn it off to revoke the key.",
    )
    added_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Added At",
        help_text="When the key was created.",
    )
    last_used_at = models.DateTimeField(
        blank=True,
        null=True,
        editable=False,
        verbose_name="Last Used At",
        help_text="When the key last called the API.",
    )
    history = HistoricalRecords()

    objects: ClassVar[ApiKeyManager] = ApiKeyManager()

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        db_table = "api_key"
        ordering = ["name"]
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"

    def set_new_key(self) -> str:
        """Gives the key a new random value, without saving it.

        Returns:
            The raw value, which is never stored or shown again.
        """
        raw_key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
        self.prefix = raw_key[:PREFIX_LENGTH]
        self.key_hash = _hash(raw_key)
        return raw_key

    def __str__(self) -> str:
        """Returns the client's name and the start of the key."""
        return f"{self.name} ({self.prefix}…)"
