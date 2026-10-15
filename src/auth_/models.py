"""Houses database models for the auth_ app."""

from django.contrib.auth.models import User
from django.db import models
from simple_history.models import HistoricalRecords

from common.models import UUIDModel


class UserProfile(UUIDModel):
    """Extends the built-in Django User model with Clerk and per-tool permissions.

    Each tool has its own permission flag. Add a flag here when you add a tool that
    needs one, and check it with the helpers in `auth_.permissions`.
    """

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")

    has_ets_permissions = models.BooleanField(
        default=False,
        verbose_name="ETS Permissions",
        help_text="Whether the user can use the Email Transfer Service.",
    )
    clerk_user_id = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        unique=True,
        verbose_name="Clerk User ID",
        help_text="The Clerk user ID for this account; populated on first Clerk login.",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
        help_text="When the user profile was last updated.",
    )
    history = HistoricalRecords()

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        verbose_name = "User Profile"
        verbose_name_plural = "User Profiles"

    def __str__(self) -> str:
        """Returns a string representation of the UserProfile object."""
        return self.user.email
