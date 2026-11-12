from django.contrib import admin, messages
from django.forms import ModelForm
from django.http import HttpRequest
from simple_history.admin import SimpleHistoryAdmin

from clinvar_submission_service.models import (
    AffiliationSettings,
    ApiKey,
    Batch,
    BatchRecord,
    Record,
)

# Tuples, since Django types fields and readonly_fields differently.
BATCH_RECORD_FIELDS = ("position", "record", "result", "scv", "errors")
RECORD_BATCH_FIELDS = ("batch", "position", "result", "scv", "errors")


class _AttemptInline(admin.TabularInline):
    """Lists attempts to send records, which only the CSS changes."""

    model = BatchRecord
    extra = 0
    can_delete = False
    show_change_link = False

    def has_add_permission(
        self,
        request: HttpRequest,  # ruff: ignore[unused-method-argument] (Django's signature.)
        obj: Batch | Record | None = None,  # ruff: ignore[unused-method-argument] (Django's signature.)
    ) -> bool:
        """Keeps staff from adding attempts by hand.

        Returns:
            False, always.
        """
        return False


class BatchRecordInline(_AttemptInline):
    """Lists a batch's records, in order, with each one's result."""

    fields = BATCH_RECORD_FIELDS
    readonly_fields = BATCH_RECORD_FIELDS


class RecordBatchInline(_AttemptInline):
    """Lists the batches a record was sent in, with each attempt's result."""

    fields = RECORD_BATCH_FIELDS
    readonly_fields = RECORD_BATCH_FIELDS


@admin.register(Batch)
class BatchAdmin(SimpleHistoryAdmin):
    list_display = [
        "slug",
        "affiliation_name",
        "made_by",
        "status",
        "clinvar_submission_id",
        "added_at",
    ]
    list_filter = ["status", "affiliation_name"]
    search_fields = ["slug", "clinvar_submission_id", "affiliation_name"]
    inlines = [BatchRecordInline]
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
    list_display = [
        "slug",
        "tool_id",
        "affiliation_name",
        "status",
        "hgvs",
        "classification",
    ]
    list_filter = ["status", "classification", "affiliation_name"]
    search_fields = [
        "slug",
        "tool_id",
        "clinvar_accession",
        "hgvs",
        "batch_records__batch__slug",
    ]
    readonly_fields = ["slug", "added_at", "updated_at"]
    inlines = [RecordBatchInline]


@admin.register(AffiliationSettings)
class AffiliationSettingsAdmin(SimpleHistoryAdmin):
    list_display = [
        "affiliation_id",
        "assertion_criteria_db",
        "assertion_criteria_id",
        "behalf_org_id",
        "release_status",
    ]
    search_fields = ["affiliation_id"]
    readonly_fields = ["updated_at"]


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
