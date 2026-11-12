from django.contrib import admin, messages
from django.forms import ModelForm
from django.http import HttpRequest
from simple_history.admin import SimpleHistoryAdmin

from affiliations_service.models import (
    CDWG,
    Affiliation,
    ApiKey,
    ClinVarSubmitterId,
    Membership,
    User,
    UserEmail,
)


@admin.register(CDWG)
class CDWGAdmin(SimpleHistoryAdmin):
    list_display = ["name", "gpm_uuid"]
    search_fields = ["name"]


class ClinVarSubmitterIdInline(admin.TabularInline):
    model = ClinVarSubmitterId
    extra = 0


class AffiliationMembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["user"]
    fields = ["user", "role", "start_date", "end_date"]


class UserMembershipInline(admin.TabularInline):
    model = Membership
    extra = 0
    autocomplete_fields = ["affiliation"]
    fields = ["affiliation", "role", "start_date", "end_date"]


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
    inlines = [ClinVarSubmitterIdInline, AffiliationMembershipInline]

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


class UserEmailInline(admin.TabularInline):
    model = UserEmail
    extra = 0


@admin.register(User)
class UserAdmin(SimpleHistoryAdmin):
    list_display = ["name", "preferred_name", "email", "institution"]
    search_fields = ["name", "preferred_name", "email", "other_emails__email", "orcid"]
    inlines = [UserEmailInline, UserMembershipInline]


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
        """Gives a new key its value and shows that value once.

        The raw key is shown in a warning message, an exception to the rule that
        flash messages are only for problems, since there's no other place to show it.
        """
        raw_key = None if change else obj.set_new_key()
        super().save_model(request, obj, form, change)
        if raw_key:
            messages.warning(
                request,
                f"Copy {obj.name}'s API key now. It won't be shown again: {raw_key}",
            )
