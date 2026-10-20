from django.contrib import admin, messages
from django.forms import ModelForm
from django.http import HttpRequest
from simple_history.admin import SimpleHistoryAdmin

from clinvar_submission_service.models import ApiKey, Record, Submission

# A tuple, since Django types fields and readonly_fields differently.
RECORD_INLINE_FIELDS = (
    "local_id",
    "record_status",
    "clinvar_accession",
    "hgvs",
    "condition_id",
    "classification",
    "mode_of_inheritance",
    "date_last_evaluated",
)


class RecordInline(admin.TabularInline):
    """Lists a submission's records, which only its payload should change."""

    model = Record
    fields = RECORD_INLINE_FIELDS
    readonly_fields = RECORD_INLINE_FIELDS
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(
        self,
        request: HttpRequest,  # ruff: ignore[unused-method-argument] (Django's signature.)
        obj: Submission | None = None,  # ruff: ignore[unused-method-argument] (Django's signature.)
    ) -> bool:
        """Keeps staff from adding records the payload doesn't have.

        Returns:
            False, always.
        """
        return False


@admin.register(Submission)
class SubmissionAdmin(SimpleHistoryAdmin):
    list_display = [
        "slug",
        "affiliation_name",
        "api_key",
        "status",
        "clinvar_submission_id",
        "added_at",
    ]
    list_filter = ["status", "affiliation_name"]
    search_fields = ["slug", "clinvar_submission_id", "affiliation_name"]
    inlines = [RecordInline]
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


@admin.register(Record)
class RecordAdmin(SimpleHistoryAdmin):
    list_display = ["local_id", "submission", "hgvs", "classification"]
    list_filter = ["classification"]
    search_fields = ["local_id", "clinvar_accession", "hgvs", "submission__slug"]


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
