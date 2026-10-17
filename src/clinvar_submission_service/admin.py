from django.contrib import admin, messages
from django.forms import ModelForm
from django.http import HttpRequest
from simple_history.admin import SimpleHistoryAdmin

from clinvar_submission_service.models import ApiKey, Submission


@admin.register(Submission)
class SubmissionAdmin(SimpleHistoryAdmin):
    list_display = ["slug", "api_key", "status", "clinvar_submission_id", "added_at"]
    list_filter = ["status"]
    search_fields = ["slug", "clinvar_submission_id"]
    readonly_fields = [
        "slug",
        "clinvar_submission_id",
        "clinvar_updated_at",
        "clinvar_error_code",
        "latest_response",
        "summary_report",
        "added_at",
        "updated_at",
        "last_polled_at",
    ]


@admin.register(ApiKey)
class ApiKeyAdmin(SimpleHistoryAdmin):
    list_display = ["name", "prefix", "is_active", "added_at", "last_used_at"]
    fields = ["name", "is_active", "prefix", "added_at", "last_used_at"]
    readonly_fields = ["prefix", "added_at", "last_used_at"]

    def save_model(
        self,
        request: HttpRequest,
        obj: ApiKey,
        form: ModelForm,
        change: bool,  # ruff: ignore[boolean-type-hint-positional-argument] (Django's signature.)
    ) -> None:
        """Gives a new key its value and shows that value once."""
        raw_key = None if change else obj.set_new_key()
        super().save_model(request, obj, form, change)
        if raw_key:
            messages.warning(
                request,
                f"Copy {obj.name}'s API key now. It won't be shown again: {raw_key}",
            )
