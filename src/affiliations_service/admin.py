from django.contrib import admin
from django.http import HttpRequest
from simple_history.admin import SimpleHistoryAdmin

from affiliations_service.models import CDWG, Affiliation, ClinVarSubmitterId


@admin.register(CDWG)
class CDWGAdmin(SimpleHistoryAdmin):
    list_display = ["name", "gpm_uuid"]
    search_fields = ["name"]


class ClinVarSubmitterIdInline(admin.TabularInline):
    model = ClinVarSubmitterId
    extra = 0


@admin.register(Affiliation)
class AffiliationAdmin(SimpleHistoryAdmin):
    list_display = [
        "affiliation_id",
        "expert_panel_id",
        "full_name",
        "type",
        "status",
        "cdwg",
        "is_deleted",
    ]
    list_filter = ["type", "status", "cdwg", "is_deleted"]
    search_fields = ["full_name", "short_name", "affiliation_id", "expert_panel_id"]
    inlines = [ClinVarSubmitterIdInline]

    # Other systems use these to refer to an affiliation, so only superusers can change
    # them, to fix mistakes.
    locked_fields = ["affiliation_id", "expert_panel_id", "type", "gpm_uuid"]

    def get_readonly_fields(
        self, request: HttpRequest, obj: Affiliation | None = None
    ) -> list[str]:
        """Locks an existing affiliation's IDs and type for everyone but superusers.

        Returns:
            The names of the read-only fields.
        """
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is not None and not getattr(request.user, "is_superuser", False):
            readonly += self.locked_fields
        return readonly
