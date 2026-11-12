"""Houses the forms on the AS's pages."""

from typing import Any

from django import forms

from affiliations_service.models import (
    CDWG,
    Affiliation,
    ClinVarSubmitterId,
    Membership,
    Person,
    PersonEmail,
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
        queryset=Person.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Coordinators",
        help_text="Search for people by name or email, and check each coordinator.",
    )

    class Meta:
        """Provides metadata."""

        model = Affiliation
        fields = ["type", "full_name", "short_name", "status", "cdwg", "gpm_uuid"]

    def picked_coordinators(self) -> list[Person]:
        """Returns the coordinators staff picked, so a re-rendered form keeps them."""
        cleaned_data = getattr(self, "cleaned_data", {})
        return list(cleaned_data.get("coordinators") or [])

    def save(self, commit: bool = True) -> Affiliation:  # ruff: ignore[boolean-type-hint-positional-argument, boolean-default-value-positional-argument] (Django's signature.)
        """Saves the affiliation and makes each picked person a coordinator.

        Returns:
            The saved affiliation.
        """
        affiliation = super().save(commit=commit)
        if commit:
            Membership.objects.bulk_create(
                Membership(
                    person=person,
                    affiliation=affiliation,
                    role=Membership.Role.COORDINATOR,
                )
                for person in self.cleaned_data["coordinators"]
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


class PersonForm(BulmaFormMixin, forms.ModelForm):
    """The fields staff fill in for a person."""

    class Meta:
        """Provides metadata."""

        model = Person
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
    Person,
    PersonEmail,
    fields=["email"],
    extra=1,
    can_delete=True,
)
OtherEmailFormSet.form = type(
    "OtherEmailForm", (BulmaFormMixin, OtherEmailFormSet.form), {}
)


class MembershipAddForm(BulmaFormMixin, forms.ModelForm):
    """Gives a person a role in an affiliation.

    The person is picked from search results, so the field is a radio list that the
    search fills in.
    """

    person = forms.ModelChoiceField(
        queryset=Person.objects.all(),
        widget=forms.RadioSelect,
        error_messages={"required": "Search for a person, then pick them."},
    )

    class Meta:
        """Provides metadata."""

        model = Membership
        fields = ["person", "role", "start_date"]
        widgets = {"start_date": forms.DateInput(attrs={"type": "date"})}

    def clean(self) -> dict[str, Any]:
        """Also checks the constraints that involve the affiliation.

        Django skips constraints on fields that aren't in the form, such as the
        affiliation, so a person holding the same role twice would otherwise only be
        caught by the database. `validate_constraints()` raises the error, and the
        form shows it.

        Returns:
            The cleaned data.
        """
        cleaned_data = super().clean() or {}
        membership = Membership(
            affiliation_id=self.instance.affiliation_id,
            person=cleaned_data.get("person"),
            role=cleaned_data.get("role"),
            start_date=cleaned_data.get("start_date"),
        )
        if membership.person_id and membership.role:  # ty: ignore[unresolved-attribute] (Django adds person_id.)
            membership.validate_constraints()
        return cleaned_data


class CdwgForm(BulmaFormMixin, forms.ModelForm):
    """The fields staff fill in for a CDWG."""

    class Meta:
        """Provides metadata."""

        model = CDWG
        fields = ["name", "gpm_uuid"]
