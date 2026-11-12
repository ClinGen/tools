"""Houses the forms on the AS's pages."""

from typing import Any

from django import forms
from django.db.models import Q

from affiliations_service.models import (
    CDWG,
    Affiliation,
    ClinVarSubmitterId,
    Membership,
    User,
    UserEmail,
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


class ActiveCDWGsMixin:
    """Offers only CDWGs that aren't deleted, plus the affiliation's current one."""

    def __init__(self, *args, **kwargs) -> None:
        """Narrows the CDWG choices."""
        super().__init__(*args, **kwargs)
        current = self.instance.cdwg_id  # ty: ignore[unresolved-attribute] (The form this mixes into edits an affiliation.)
        self.fields["cdwg"].queryset = CDWG.objects.filter(  # ty: ignore[unresolved-attribute] (The form this mixes into has fields.)
            Q(is_deleted=False) | Q(pk=current)
        )


class AffiliationCreateForm(ActiveCDWGsMixin, BulmaFormMixin, forms.ModelForm):
    """The fields staff fill in for a new affiliation. The AS assigns its IDs.

    Staff can also pick the affiliation's coordinators, who get coordinator
    memberships when it's saved. Other members are added from the affiliation's page.
    """

    coordinators = forms.ModelMultipleChoiceField(
        queryset=User.objects.active(),
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


class AffiliationEditForm(ActiveCDWGsMixin, BulmaFormMixin, forms.ModelForm):
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


class UserForm(BulmaFormMixin, forms.ModelForm):
    """The fields staff fill in for a user."""

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


OtherEmailFormSet = forms.inlineformset_factory(
    User,
    UserEmail,
    fields=["email"],
    extra=1,
    can_delete=True,
)
OtherEmailFormSet.form = type(
    "OtherEmailForm", (BulmaFormMixin, OtherEmailFormSet.form), {}
)


class MembershipAddForm(BulmaFormMixin, forms.ModelForm):
    """Gives a user a role in an affiliation.

    The user is picked from search results, so the field is a radio list that the
    search fills in.
    """

    user = forms.ModelChoiceField(
        queryset=User.objects.active(),
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
