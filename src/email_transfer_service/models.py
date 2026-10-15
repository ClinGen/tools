"""Houses database models for the email_transfer_service app."""

from django.contrib.auth.models import User
from django.db import models
from django.urls import reverse
from simple_history.models import HistoricalRecords


class EmailTransfer(models.Model):
    """One run of a transfer from an old email to a new one.

    It's saved before the first change to AWS, and each step's result is recorded as
    the step finishes, so a transfer that fails partway shows which steps ran.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "In Progress"
        SUCCEEDED = "succeeded", "Succeeded"
        FAILED = "failed", "Failed"

    slug = models.SlugField(
        default="",
        max_length=7,
        verbose_name="Human-Readable ID",
        help_text="The human-readable ID for the object.",
    )
    old_email = models.EmailField(
        verbose_name="Old Email",
        help_text="The email the user's account is moving from.",
    )
    new_email = models.EmailField(
        verbose_name="New Email",
        help_text="The email the user's account is moving to.",
    )
    ran_by = models.ForeignKey(
        User,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="email_transfers",
        verbose_name="Ran By",
        help_text="The staff member who ran the transfer.",
    )
    old_username = models.CharField(
        blank=True,
        default="",
        max_length=128,
        verbose_name="Old Cognito Username",
        help_text="The Cognito username of the old email's user, which is disabled.",
    )
    new_username = models.CharField(
        blank=True,
        default="",
        max_length=128,
        verbose_name="New Cognito Username",
        help_text="The Cognito username of the new email's user, which is enabled.",
    )
    old_record_pk = models.CharField(
        blank=True,
        default="",
        max_length=128,
        verbose_name="Old Record PK",
        help_text="The PK of the DynamoDB user record that moves to the new email.",
    )
    retired_record_pk = models.CharField(
        blank=True,
        default="",
        max_length=128,
        verbose_name="Retired Record PK",
        help_text=(
            "The PK of the new email's 'requested activation' record, if it had one "
            "and it was retired."
        ),
    )
    dry_run = models.BooleanField(
        default=True,
        verbose_name="Dry Run",
        help_text="Whether the transfer skipped its changes to AWS.",
    )
    status = models.CharField(
        choices=Status.choices,
        default=Status.PENDING,
        max_length=9,
        verbose_name="Status",
        help_text="Whether the transfer is running, finished, or stopped at a failure.",
    )
    steps = models.JSONField(
        default=list,
        blank=True,
        verbose_name="Steps",
        help_text=(
            "Each step of the transfer: a summary for staff, a technical description, "
            "its result, and any error."
        ),
    )
    error = models.TextField(
        blank=True,
        default="",
        verbose_name="Error",
        help_text="The error from the step that failed, if one did.",
    )
    added_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Added At",
        help_text="When the transfer started.",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
        help_text="When the transfer was last updated.",
    )
    history = HistoricalRecords()

    class Meta:
        """Provides metadata."""

        db_table = "email_transfer"
        ordering = ["-added_at"]
        verbose_name = "Email Transfer"
        verbose_name_plural = "Email Transfers"

    def __str__(self) -> str:
        """Returns the transfer's human-readable ID."""
        return self.slug

    def save(self, *args, **kwargs) -> None:
        """Adds a human-readable ID."""
        super().save(*args, **kwargs)
        if not self.slug:
            self.slug = f"T{self.pk:06d}"
            self.save(update_fields=["slug"])

    def get_absolute_url(self) -> str:
        """Returns the transfer's detail page."""
        return reverse("ets:detail", kwargs={"slug": self.slug})
