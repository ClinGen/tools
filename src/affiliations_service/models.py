"""Houses database models for the affiliations_service app.

"The Affiliations Service" in `docs/design.md` describes the ID scheme and the rules
these models follow.
"""

from typing import ClassVar

from django.db import models, transaction
from django.db.models.functions import Lower
from simple_history.models import HistoricalRecords

from common.models import UUIDModel

FIRST_AFFILIATION_ID = 10000
AFFILIATION_ID_LIMIT = 20000
GCEP_OFFSET = 30000
VCEP_OFFSET = 40000


class CDWG(UUIDModel):
    """A Clinical Domain Working Group, such as Cardiovascular or Hereditary Cancer."""

    name = models.CharField(
        max_length=255,
        verbose_name="Name",
        help_text="The CDWG's name. No two CDWGs share a name, ignoring case.",
    )
    gpm_uuid = models.UUIDField(
        blank=True,
        null=True,
        unique=True,
        verbose_name="GPM UUID",
        help_text="The UUID the GPM uses for this CDWG, if it has one.",
    )
    added_at = models.DateTimeField(auto_now_add=True, verbose_name="Added At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")
    history = HistoricalRecords()

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        verbose_name = "CDWG"
        verbose_name_plural = "CDWGs"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(Lower("name"), name="as_cdwg_unique_name"),
        ]

    def __str__(self) -> str:
        """Returns the CDWG's name."""
        return self.name


class AffiliationQuerySet(models.QuerySet):
    """Adds soft deletion to affiliation querysets."""

    def active(self) -> "AffiliationQuerySet":
        """Returns the affiliations that haven't been deleted."""
        return self.filter(is_deleted=False)

    def delete(self) -> tuple[int, dict[str, int]]:
        """Marks each affiliation deleted instead of deleting it.

        Returns:
            Zero rows deleted, as Django's delete() would report it.
        """
        for affiliation in self:
            affiliation.delete()
        return 0, {}


class AffiliationManager(models.Manager):
    """Returns `AffiliationQuerySet`s, which delete softly."""

    def get_queryset(self) -> AffiliationQuerySet:
        """Returns all affiliations, including deleted ones."""
        return AffiliationQuerySet(self.model, using=self._db)

    def active(self) -> AffiliationQuerySet:
        """Returns the affiliations that haven't been deleted."""
        return self.get_queryset().active()


class Affiliation(UUIDModel):
    """A group that curates for ClinGen, such as a VCEP or a GCEP.

    The affiliation ID and the expert panel ID are assigned on creation. Affiliations
    are never deleted; `delete()` marks them deleted instead.
    """

    class Type(models.TextChoices):
        VCEP = "VCEP", "VCEP"
        GCEP = "GCEP", "GCEP"
        SC_VCEP = "SC_VCEP", "SC-VCEP"
        INDEPENDENT_CURATION = "INDEPENDENT_CURATION", "Independent Curation Group"

    class Status(models.TextChoices):
        APPLYING = "APPLYING", "Applying"
        ACTIVE = "ACTIVE", "Active"
        INACTIVE = "INACTIVE", "Inactive"
        RETIRED = "RETIRED", "Retired"
        ARCHIVED = "ARCHIVED", "Archived"

    type = models.CharField(
        choices=Type.choices,
        max_length=32,
        verbose_name="Type",
        help_text="What kind of group the affiliation is.",
    )
    affiliation_id = models.PositiveIntegerField(
        blank=True,
        verbose_name="Affiliation ID",
        help_text=(
            "The affiliation's ID, from 10000 to 19999. A VCEP and a GCEP that are one "
            "group share it."
        ),
    )
    expert_panel_id = models.PositiveIntegerField(
        blank=True,
        null=True,
        unique=True,
        verbose_name="Expert Panel ID",
        help_text=(
            "In the 40000 range for a GCEP or the 50000 range for a VCEP or SC-VCEP. "
            "Independent curation groups have none."
        ),
    )
    full_name = models.CharField(max_length=255, verbose_name="Full Name")
    short_name = models.CharField(
        blank=True,
        default="",
        max_length=255,
        verbose_name="Short Name",
    )
    status = models.CharField(
        choices=Status.choices,
        default=Status.APPLYING,
        max_length=16,
        verbose_name="Status",
    )
    cdwg = models.ForeignKey(
        CDWG,
        on_delete=models.PROTECT,
        related_name="affiliations",
        verbose_name="CDWG",
        help_text="The Clinical Domain Working Group the affiliation belongs to.",
    )
    gpm_uuid = models.UUIDField(
        blank=True,
        null=True,
        unique=True,
        verbose_name="GPM UUID",
        help_text="The UUID the GPM uses for this affiliation, if it has one.",
    )
    is_deleted = models.BooleanField(
        default=False,
        verbose_name="Deleted",
        help_text="Deleted affiliations are kept, but left out of lists.",
    )
    added_at = models.DateTimeField(auto_now_add=True, verbose_name="Added At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")
    history = HistoricalRecords()

    objects: ClassVar[AffiliationManager] = AffiliationManager()

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        ordering = ["affiliation_id", "type"]
        constraints = [
            models.UniqueConstraint(
                fields=["affiliation_id", "type"],
                name="as_affiliation_unique_id_per_type",
            ),
        ]

    def __str__(self) -> str:
        """Returns the affiliation's full name."""
        return self.full_name

    def save(self, *args, **kwargs) -> None:
        """Assigns the affiliation's IDs on creation, then saves it."""
        with transaction.atomic():
            if self.affiliation_id is None:
                self.affiliation_id = self._next_affiliation_id()
            if self._state.adding and self.expert_panel_id is None:
                self.expert_panel_id = self._derived_expert_panel_id()
            super().save(*args, **kwargs)

    def delete(self, *_args, **_kwargs) -> tuple[int, dict[str, int]]:
        """Marks the affiliation deleted instead of deleting it.

        Returns:
            Zero rows deleted, as Django's delete() would report it.
        """
        self.is_deleted = True
        self.save()
        return 0, {}

    @staticmethod
    def _next_affiliation_id() -> int:
        """Returns one more than the highest affiliation ID, or 10000 if there's none.

        Raises:
            ValueError: If the next ID would reach 20000.
        """
        highest = Affiliation.objects.aggregate(models.Max("affiliation_id"))[
            "affiliation_id__max"
        ]
        next_id = FIRST_AFFILIATION_ID if highest is None else highest + 1
        if next_id >= AFFILIATION_ID_LIMIT:
            error_message = f"The next affiliation ID, {next_id}, would be too high."
            raise ValueError(error_message)
        return next_id

    def _derived_expert_panel_id(self) -> int | None:
        """Returns the expert panel ID that goes with the type and affiliation ID."""
        if self.type == self.Type.GCEP:
            return self.affiliation_id + GCEP_OFFSET
        if self.type in {self.Type.VCEP, self.Type.SC_VCEP}:
            return self.affiliation_id + VCEP_OFFSET
        return None


class ClinVarSubmitterId(UUIDModel):
    """A ClinVar submitter ID that an affiliation submits to ClinVar with."""

    affiliation = models.ForeignKey(
        Affiliation,
        on_delete=models.CASCADE,
        related_name="clinvar_submitter_ids",
        verbose_name="Affiliation",
    )
    submitter_id = models.CharField(
        max_length=50,
        verbose_name="ClinVar Submitter ID",
    )
    history = HistoricalRecords()

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        verbose_name = "ClinVar Submitter ID"
        verbose_name_plural = "ClinVar Submitter IDs"
        ordering = ["submitter_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["affiliation", "submitter_id"],
                name="as_submitter_id_unique_per_affiliation",
            ),
        ]

    def __str__(self) -> str:
        """Returns the submitter ID."""
        return self.submitter_id
