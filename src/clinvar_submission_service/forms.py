from django import forms
from django.core.exceptions import ValidationError

from clinvar_submission_service.models import AffiliationSettings

CHOICE_ERROR = "Pick one of the listed choices."


class AffiliationSettingsForm(forms.ModelForm):
    class Meta:
        model = AffiliationSettings
        fields = (
            "assertion_criteria_db",
            "assertion_criteria_id",
            "behalf_org_id",
            "release_status",
        )
        error_messages = {
            "assertion_criteria_db": {"invalid_choice": CHOICE_ERROR},
            "release_status": {"invalid_choice": CHOICE_ERROR},
        }

    def clean(self) -> dict:
        """Makes sure the assertion criteria have both a database and an ID, or neither.

        Returns:
            The cleaned data.

        Raises:
            ValidationError: If only one of the two is given.
        """
        cleaned_data = super().clean() or {}
        has_db = bool(cleaned_data.get("assertion_criteria_db"))
        has_id = bool(cleaned_data.get("assertion_criteria_id"))
        # Skip the check if the database was rejected, which already has its error.
        if "assertion_criteria_db" not in self.errors and has_db != has_id:
            error_message = (
                "Enter both the assertion criteria's database and its ID, or neither."
            )
            raise ValidationError(error_message)
        return cleaned_data
