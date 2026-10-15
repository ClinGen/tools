from django import forms
from django.core.exceptions import ValidationError


def validate_plain_email(email: str) -> None:
    """Rejects emails that would break Cognito's filter syntax.

    Raises:
        ValidationError: If the email contains a quote or a backslash.
    """
    if '"' in email or "\\" in email:
        error_message = "Enter an email without quotes or backslashes."
        raise ValidationError(error_message)


class TransferForm(forms.Form):
    old_email = forms.EmailField(
        label="Old Email",
        help_text="The email the user's account is moving from.",
        validators=[validate_plain_email],
    )
    new_email = forms.EmailField(
        label="New Email",
        help_text="The email the user's account is moving to.",
        validators=[validate_plain_email],
    )

    def clean(self) -> dict:
        """Makes sure the two emails differ.

        Returns:
            The cleaned data.

        Raises:
            ValidationError: If the emails are the same.
        """
        cleaned_data = super().clean() or {}
        old_email = cleaned_data.get("old_email", "")
        new_email = cleaned_data.get("new_email", "")
        if old_email and old_email.lower() == new_email.lower():
            error_message = "The old and new emails must differ."
            raise ValidationError(error_message)
        return cleaned_data
