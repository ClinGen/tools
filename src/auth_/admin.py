from django.contrib import admin
from django.contrib.auth.models import Group
from simple_history.admin import SimpleHistoryAdmin

from auth_.models import UserProfile

# We don't use groups.
admin.site.unregister(Group)


@admin.register(UserProfile)
class UserProfileAdmin(SimpleHistoryAdmin):
    list_display = ["user", "has_ets_permissions"]
    fields = ["user", "has_ets_permissions", "clerk_user_id"]
