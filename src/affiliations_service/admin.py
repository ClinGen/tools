from django.contrib import admin
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
