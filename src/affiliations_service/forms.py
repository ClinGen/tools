"""Houses the forms on the AS's pages."""

from typing import Any

from django import forms
from django.core.exceptions import ValidationError
from django.utils.html import format_html

from affiliations_service.duplicates import similar_users
from affiliations_service.models import (
    CDWG,
    Affiliation,
    ClinVarSubmitterId,
    Membership,
    User,
    UserEmail,
    user_with_email,
)


class BulmaFormMixin:
    """Adds Bulma's classes to a form's text inputs."""

    def __init__(self, *args, **kwargs) -> None:
        """Sets each text-like widget's class to Bulma's `input` or `textarea`."""
        super().__init__(*args, **kwargs)
        for field in self.fields.values():  # ty: ignore[unresolved-attribute] (The class this mixes into has fields.)
            widget = field.widget
            if isinstance(widget, forms.Textarea):
                widget.attrs.setdefault("class", "textarea")
            elif isinstance(widget, forms.widgets.Input) and not isinstance(
                widget, forms.CheckboxInput
            ):
                widget.attrs.setdefault("class", "input")


class AffiliationCreateForm(BulmaFormMixin, forms.ModelForm):
    """The fields staff fill in for a new affiliation. The AS assigns its IDs.

    Staff can also pick the affiliation's coordinators, who get coordinator
    memberships when it's saved. Other members are added from the affiliation's page.
    """

    coordinators = forms.ModelMultipleChoiceField(
        queryset=User.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Coordinators",
        help_text="Search for users by name or email, and check each coordinator.",
    )

    class Meta:
        """Provides metadata."""

        model = Affiliation
        fields = ["type", "full_name", "short_name", "status", "cdwg", "gpm_uuid"]

    def picked_coordinators(self) -> list[User]:
        """Returns the coordinators staff picked, so a re-rendered form keeps them."""
        cleaned_data = getattr(self, "cleaned_data", {})
        return list(cleaned_data.get("coordinators") or [])

    def save(self, commit: bool = True) -> Affiliation:  # ruff: ignore[boolean-type-hint-positional-argument, boolean-default-value-positional-argument] (Django's signature.)
        """Saves the affiliation and makes each picked user a coordinator.

        Returns:
            The saved affiliation.
        """
        affiliation = super().save(commit=commit)
        if commit:
            Membership.objects.bulk_create(
                Membership(
                    user=user,
                    affiliation=affiliation,
                    role=Membership.Role.COORDINATOR,
                )
                for user in self.cleaned_data["coordinators"]
            )
        return affiliation


class AffiliationEditForm(BulmaFormMixin, forms.ModelForm):
    """The fields staff can change on an affiliation.

    The IDs, type, and GPM UUID aren't here, since other systems refer to an
    affiliation by them. Superusers change them in the Django admin.
    """

    class Meta:
        """Provides metadata."""

        model = Affiliation
        fields = ["full_name", "short_name", "status", "cdwg"]


SubmitterIdFormSet = forms.inlineformset_factory(
    Affiliation,
    ClinVarSubmitterId,
    fields=["submitter_id"],
    extra=1,
    can_delete=True,
)
SubmitterIdFormSet.form = type(
    "SubmitterIdForm", (BulmaFormMixin, SubmitterIdFormSet.form), {}
)


class TakenEmailMixin:
    """Refuses an email someone else has, naming and linking the user who has it."""

    def owner(self) -> User | None:
        """Returns the user whose email this form's email may already be.

        Returns:
            The user, or None if there's no one to leave out.
        """
        return None

    def clean_email(self) -> str:
        """Checks that no one else has the email, primary or other.

        Returns:
            The email.

        Raises:
            ValidationError: If someone else has it, with a link to them.
        """
        email = self.cleaned_data["email"]  # ty: ignore[unresolved-attribute] (The class this mixes into has cleaned_data.)
        if email and (other := user_with_email(email, user=self.owner())):
            message = format_html(
                '<a href="{}">{}</a> already has this email.',
                other.get_absolute_url(),
                other.name,
            )
            raise ValidationError(message)
        return email


class UserForm(TakenEmailMixin, BulmaFormMixin, forms.ModelForm):
    """The fields staff fill in for a user.

    A new user whose name is like an existing user's isn't saved unless staff
    confirm with Add Anyway; `similar` holds the possible matches.
    """

    class Meta:
        """Provides metadata."""

        model = User
        fields = [
            "name",
            "preferred_name",
            "email",
            "institution",
            "orcid",
            "credentials",
            "gpm_uuid",
        ]

    def __init__(self, *args, allow_similar_name: bool = False, **kwargs) -> None:
        """Sets whether a new user may have a name like an existing user's.

        Args:
            *args: The form's arguments.
            allow_similar_name: Whether staff chose Add Anyway.
            **kwargs: The form's keyword arguments.
        """
        super().__init__(*args, **kwargs)
        self.allow_similar_name = allow_similar_name
        self.similar: list[User] = []

    def owner(self) -> User | None:
        """Returns the user being edited, if any.

        Returns:
            The user, or None for a new one.
        """
        return self.instance if self.instance.pk else None

    def clean(self) -> dict[str, Any]:
        """Checks that a new user's name isn't like an existing user's.

        Returns:
            The cleaned data.

        Raises:
            ValidationError: If the name is like someone's and staff haven't chosen
                Add Anyway.
        """
        cleaned_data = super().clean() or {}
        if self.instance._state.adding and not self.allow_similar_name:  # ruff: ignore[private-member-access]
            self.similar = similar_users(
                cleaned_data.get("name", ""),
                preferred_name=cleaned_data.get("preferred_name", ""),
            )
            if self.similar:
                message = "This user might already be in the AS. Check the users below."
                raise ValidationError(message)
        return cleaned_data


class OtherEmailForm(TakenEmailMixin, BulmaFormMixin, forms.ModelForm):
    """One of a user's other emails."""

    def owner(self) -> User | None:
        """Returns the user whose email this is, if they've been saved.

        Returns:
            The user, or None for a new one.
        """
        user_id = self.instance.user_id
        return self.instance.user if user_id is not None else None


OtherEmailFormSet = forms.inlineformset_factory(
    User,
    UserEmail,
    form=OtherEmailForm,
    fields=["email"],
    extra=1,
    can_delete=True,
)


class MembershipAddForm(BulmaFormMixin, forms.ModelForm):
    """Gives a user a role in an affiliation.

    The user is picked from search results, so the field is a radio list that the
    search fills in.
    """

    user = forms.ModelChoiceField(
        queryset=User.objects.all(),
        widget=forms.RadioSelect,
        error_messages={"required": "Search for a user, then pick them."},
    )

    class Meta:
        """Provides metadata."""

        model = Membership
        fields = ["user", "role", "start_date"]
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"})}

    def clean(self) -> dict[str, Any]:
        """Also checks the constraints that involve the affiliation.

        Django skips constraints on fields that aren't in the form, such as the
        affiliation, so a user holding the same role twice would otherwise only be
        caught by the database. `validate_constraints()` raises the error, and the
        form shows it.

        Returns:
            The cleaned data.
        """
        cleaned_data = super().clean() or {}
        membership = Membership(
            affiliation_id=self.instance.affiliation_id,
            user=cleaned_data.get("user"),
            role=cleaned_data.get("role"),
            start_date=cleaned_data.get("start_date"),
        )
        if membership.user_id and membership.role:  # ty: ignore[unresolved-attribute] (Django adds user_id.)
            membership.validate_constraints()
        return cleaned_data


class CDWGForm(BulmaFormMixin, forms.ModelForm):
    """The fields staff fill in for a CDWG."""

    class Meta:
        """Provides metadata."""

        model = CDWG
        fields = ["name", "gpm_uuid"]
