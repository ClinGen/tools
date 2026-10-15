from django.contrib import admin
from simple_history.admin import SimpleHistoryAdmin

from email_transfer_service.models import EmailTransfer


@admin.register(EmailTransfer)
class EmailTransferAdmin(SimpleHistoryAdmin):
    list_display = ["slug", "old_email", "new_email", "status", "dry_run", "added_at"]
    readonly_fields = ["slug", "added_at", "updated_at"]
