from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from clinvar_submission_service.models import Submission


@admin.register(Submission)
class SubmissionAdmin(SimpleHistoryAdmin):
    list_display = ["slug", "status", "clinvar_submission_id", "added_at"]
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
