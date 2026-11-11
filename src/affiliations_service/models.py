"""Houses database models for the affiliations_service app.

"The Affiliations Service" in `docs/design.md` describes the ID scheme and the rules
these models follow.
"""

import datetime
import uuid
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.db.models.functions import Lower
from django.utils import timezone
from simple_history.models import HistoricalRecords

from common.models import UUIDModel

FIRST_AFFILIATION_ID = 10000
AFFILIATION_ID_LIMIT = 20000
GCEP_OFFSET = 30000
VCEP_OFFSET = 40000
GCEP_RANGE = range(40000, 50000)
VCEP_RANGE = range(50000, 60000)
SOMATIC_CANCER_CDWG = "Somatic Cancer"
NO_CDWG = "None"


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
        error_messages={"unique": "Another CDWG already has this GPM UUID."},
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
            models.UniqueConstraint(
                Lower("name"),
                name="as_cdwg_unique_name",
                violation_error_message="There's already a CDWG with this name.",
            ),
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
        error_messages={
            "unique": "Another affiliation already has this expert panel ID."
        },
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
        error_messages={"unique": "Another affiliation already has this GPM UUID."},
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
    cdwg_id: uuid.UUID | None  # Django adds this for the cdwg foreign key.

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        ordering = ["affiliation_id", "type"]
        constraints = [
            models.UniqueConstraint(
                fields=["affiliation_id", "type"],
                name="as_affiliation_unique_id_per_type",
                violation_error_message=(
                    "Another affiliation of this type already has this affiliation ID."
                ),
            ),
        ]

    def __str__(self) -> str:
        """Returns the affiliation's full name."""
        return self.full_name

    def clean(self) -> None:
        """Checks the rules in "The Affiliations Service" in `docs/design.md`.

        Raises:
            ValidationError: If the affiliation breaks a rule, keyed by field.
        """
        errors: dict[str, str] = {}
        is_independent = self.type == self.Type.INDEPENDENT_CURATION
        if is_independent and self.gpm_uuid:
            errors["gpm_uuid"] = "An independent curation group can't have a GPM UUID."
        if self.cdwg_id is not None:
            cdwg_name = self.cdwg.name
            if self.type == self.Type.SC_VCEP and cdwg_name != SOMATIC_CANCER_CDWG:
                errors["cdwg"] = (
                    f"An SC-VCEP must be in the {SOMATIC_CANCER_CDWG} CDWG."
                )
            if is_independent and cdwg_name != NO_CDWG:
                errors["cdwg"] = (
                    "An independent curation group must be in the CDWG named "
                    f"{NO_CDWG}."
                )
        errors.update(self._id_errors())
        if errors:
            raise ValidationError(errors)

    def _id_errors(self) -> dict[str, str]:
        """Checks that the affiliation's IDs are in range and go together.

        New affiliations get their IDs on save, so this only matters when someone
        sets them by hand, such as a superuser fixing a mistake in the Django admin.

        Returns:
            Error messages keyed by field.
        """
        errors: dict[str, str] = {}
        affiliation_id, expert_panel_id = self.affiliation_id, self.expert_panel_id
        if affiliation_id is not None and not (
            FIRST_AFFILIATION_ID <= affiliation_id < AFFILIATION_ID_LIMIT
        ):
            errors["affiliation_id"] = "The affiliation ID must be from 10000 to 19999."
        if expert_panel_id is None:
            return errors
        expected_range = {
            self.Type.GCEP: GCEP_RANGE,
            self.Type.VCEP: VCEP_RANGE,
            self.Type.SC_VCEP: VCEP_RANGE,
        }.get(self.type)
        if expected_range is None:
            errors["expert_panel_id"] = (
                "An independent curation group can't have an expert panel ID."
            )
        elif expert_panel_id not in expected_range:
            errors["expert_panel_id"] = (
                f"A {self.Type(self.type).label}'s expert panel ID must be from "
                f"{expected_range.start} to {expected_range.stop - 1}."
            )
        elif (
            affiliation_id is not None
            and affiliation_id % 1000 != expert_panel_id % 1000
        ):
            errors["expert_panel_id"] = (
                "The last three digits of the expert panel ID must match the "
                "affiliation ID's."
            )
        return errors

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


ORCID_VALIDATOR = RegexValidator(
    r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$",
    "Enter an ORCID iD like 0000-0002-1825-0097.",
)
DUPLICATE_EMAIL_MESSAGE = "Someone already has this email."


def email_is_taken(email: str, *, person: "Person | None" = None) -> bool:
    """Reports whether a person other than the given one has an email.

    Emails are compared ignoring case, and both primary and other emails count.

    Args:
        email: The email to look for.
        person: The person who may already have the email, if any.

    Returns:
        True if someone else has the email.
    """
    people = Person.objects.filter(email__iexact=email)
    other_emails = PersonEmail.objects.filter(email__iexact=email)
    if person is not None and person.pk is not None:
        people = people.exclude(pk=person.pk)
        other_emails = other_emails.exclude(person=person)
    return people.exists() or other_emails.exists()


class Person(UUIDModel):
    """A person in ClinGen's affiliations, such as a coordinator or a curator.

    People are never deleted. Their fields are a starting point; we expect to add more.
    """

    name = models.CharField(max_length=255, verbose_name="Name")
    preferred_name = models.CharField(
        blank=True,
        default="",
        max_length=255,
        verbose_name="Preferred Name",
        help_text="What the person likes to be called, if it differs from their name.",
    )
    email = models.EmailField(
        verbose_name="Email",
        help_text="The person's main email. No two people share an email.",
    )
    institution = models.CharField(
        blank=True,
        default="",
        max_length=255,
        verbose_name="Institution",
    )
    orcid = models.CharField(
        blank=True,
        default="",
        max_length=19,
        validators=[ORCID_VALIDATOR],
        verbose_name="ORCID iD",
        help_text="Like 0000-0002-1825-0097.",
    )
    credentials = models.CharField(
        blank=True,
        default="",
        max_length=255,
        verbose_name="Credentials",
        help_text='Degrees and certifications, such as "PhD, CGC".',
    )
    gpm_uuid = models.UUIDField(
        blank=True,
        null=True,
        unique=True,
        error_messages={"unique": "Another person already has this GPM UUID."},
        verbose_name="GPM UUID",
        help_text="The UUID the GPM uses for this person, if it has one.",
    )
    added_at = models.DateTimeField(auto_now_add=True, verbose_name="Added At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")
    history = HistoricalRecords()

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        verbose_name_plural = "People"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="as_person_unique_email",
                violation_error_message=DUPLICATE_EMAIL_MESSAGE,
            ),
            models.UniqueConstraint(
                fields=["orcid"],
                condition=~models.Q(orcid=""),
                name="as_person_unique_orcid",
                violation_error_message="Another person already has this ORCID iD.",
            ),
        ]

    def __str__(self) -> str:
        """Returns the person's preferred name, or their name if they have none."""
        return self.preferred_name or self.name

    def clean(self) -> None:
        """Checks that no one else has the person's email as an other email.

        Raises:
            ValidationError: If someone else has the email.
        """
        if self.email and email_is_taken(self.email, person=self):
            raise ValidationError({"email": DUPLICATE_EMAIL_MESSAGE})


class PersonEmail(UUIDModel):
    """An email a person has besides their main one."""

    person = models.ForeignKey(
        Person,
        on_delete=models.CASCADE,
        related_name="other_emails",
        verbose_name="Person",
    )
    email = models.EmailField(verbose_name="Email")
    history = HistoricalRecords()

    person_id: uuid.UUID | None  # Django adds this for the person foreign key.

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        verbose_name = "Other Email"
        verbose_name_plural = "Other Emails"
        ordering = ["email"]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                name="as_person_email_unique_email",
                violation_error_message=DUPLICATE_EMAIL_MESSAGE,
            ),
        ]

    def __str__(self) -> str:
        """Returns the email."""
        return self.email

    def clean(self) -> None:
        """Checks that no one else has this email.

        Raises:
            ValidationError: If someone else has the email.
        """
        person = self.person if self.person_id is not None else None
        if self.email and email_is_taken(self.email, person=person):
            raise ValidationError({"email": DUPLICATE_EMAIL_MESSAGE})


class MembershipQuerySet(models.QuerySet):
    """Adds a filter for current memberships."""

    def current(self) -> "MembershipQuerySet":
        """Returns the memberships with no end date or an end date in the future."""
        today = timezone.localdate()
        return self.filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gt=today)
        )


class MembershipManager(models.Manager):
    """Returns `MembershipQuerySet`s."""

    def get_queryset(self) -> MembershipQuerySet:
        """Returns all memberships, including ended ones."""
        return MembershipQuerySet(self.model, using=self._db)

    def current(self) -> MembershipQuerySet:
        """Returns the memberships with no end date or an end date in the future."""
        return self.get_queryset().current()


class Membership(UUIDModel):
    """A role a person holds in an affiliation.

    A person who holds two roles in an affiliation has two memberships. Memberships
    aren't deleted; ending one sets its end date, so the AS remembers who was in a
    group and when.
    """

    class Role(models.TextChoices):
        COORDINATOR = "COORDINATOR", "Coordinator"
        APPROVER = "APPROVER", "Approver"
        CURATOR = "CURATOR", "Curator"

    person = models.ForeignKey(
        Person,
        on_delete=models.PROTECT,
        related_name="memberships",
        verbose_name="Person",
    )
    affiliation = models.ForeignKey(
        Affiliation,
        on_delete=models.PROTECT,
        related_name="memberships",
        verbose_name="Affiliation",
    )
    role = models.CharField(choices=Role.choices, max_length=16, verbose_name="Role")
    start_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="Start Date",
        help_text="When the person started in this role, if known.",
    )
    end_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="End Date",
        help_text="When the person's time in this role ends. Leave blank if it hasn't.",
    )
    added_at = models.DateTimeField(auto_now_add=True, verbose_name="Added At")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated At")
    history = HistoricalRecords()

    objects: ClassVar[MembershipManager] = MembershipManager()

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        ordering = ["role", "person__name"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(start_date__isnull=True)
                | models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="as_membership_ends_after_it_starts",
                violation_error_message="The end date can't be before the start date.",
            ),
            models.UniqueConstraint(
                fields=["person", "affiliation", "role"],
                condition=models.Q(end_date__isnull=True),
                name="as_membership_one_open_role",
                violation_error_message=(
                    "This person already holds this role in this affiliation."
                ),
            ),
        ]

    def __str__(self) -> str:
        """Returns who holds which role where."""
        return f"{self.person}, {self.get_role_display()}, {self.affiliation}"  # ty: ignore[unresolved-attribute] (Django adds get_role_display.)

    @property
    def is_current(self) -> bool:
        """Whether the membership has no end date or ends in the future."""
        return self.end_date is None or self.end_date > timezone.localdate()

    def end(self, on: datetime.date | None = None) -> None:
        """Ends the membership by setting its end date.

        Args:
            on: The end date. Defaults to today.
        """
        self.end_date = on or timezone.localdate()
        self.save()
