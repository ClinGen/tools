"""Houses the forms on the AS's pages."""

from django import forms

from affiliations_service.models import Affiliation, ClinVarSubmitterId


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
    """The fields staff fill in for a new affiliation. The AS assigns its IDs."""

    class Meta:
        """Provides metadata."""

        model = Affiliation
        fields = ["type", "full_name", "short_name", "status", "cdwg", "gpm_uuid"]


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
