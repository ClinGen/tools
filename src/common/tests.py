import uuid
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.test import TestCase, override_settings
from django.urls import include, path, reverse

from auth_.models import UserProfile
from common.models import make_slug
from config import urls as project_urls


def fake_ets_index(request: HttpRequest) -> HttpResponse:  # ruff: ignore[unused-function-argument]
    """Stands in for the ETS's index view.

    Returns:
        A response with the text "ETS".
    """
    return HttpResponse("ETS")


urlpatterns = [
    *project_urls.urlpatterns,
    path("ets/", include(([path("", fake_ets_index, name="index")], "ets"))),
]


@override_settings(ROOT_URLCONF="common.tests")
@patch("common.middleware.sentry_sdk.set_tag")
class ToolTagMiddlewareTest(TestCase):
    def test_tags_a_tool_request_with_the_tool(self, mock_set_tag: MagicMock):
        self.client.get("/ets/")
        mock_set_tag.assert_called_once_with("tool", "ets")

    def test_leaves_the_landing_page_untagged(self, mock_set_tag: MagicMock):
        self.client.get("/")
        mock_set_tag.assert_not_called()

    def test_leaves_sign_in_untagged(self, mock_set_tag: MagicMock):
        self.client.get("/auth/login")
        mock_set_tag.assert_not_called()


class BackupStorageTest(TestCase):
    def test_backups_go_to_a_local_directory_without_a_bucket(self):
        storage = settings.STORAGES["dbbackup"]
        self.assertEqual(
            storage["BACKEND"], "django.core.files.storage.FileSystemStorage"
        )
        self.assertEqual(
            storage["OPTIONS"]["location"], settings.BASE_DIR.parent / "backups"
        )

    def test_backup_names_start_with_the_subdomain(self):
        self.assertEqual(settings.DBBACKUP_HOSTNAME, settings.SUBDOMAIN)
        self.assertTrue(
            settings.DBBACKUP_FILENAME_TEMPLATE.startswith("daily/{servername}-")
        )


class MakeSlugTest(TestCase):
    def test_slug_is_the_prefix_and_eight_hex_characters(self):
        id_ = uuid.UUID("3f2a9c1e-0000-4000-8000-000000000000")
        self.assertEqual(make_slug("T", id_), "T3f2a9c1e")


class UserProfileIdTest(TestCase):
    def test_profile_and_its_history_have_uuid_ids(self):
        user = User.objects.create_user(username="staff@example.com")
        profile = UserProfile.objects.create(user=user)
        self.assertIsInstance(profile.pk, uuid.UUID)
        self.assertIsInstance(profile.history.first().history_id, uuid.UUID)  # type: ignore


class TooltipTest(TestCase):
    """The tooltip template shows its text in a Tippy tooltip, never beside it."""

    def test_has_the_text_in_a_tooltip_and_for_screen_readers(self):
        html = render_to_string(
            "common/tooltip.html", {"icon_name": "info-circle", "text": "Some help."}
        )
        self.assertIn('data-tippy-content="Some help."', html)
        self.assertIn('<span class="is-sr-only">Some help.</span>', html)
        self.assertIn("bi-info-circle", html)
        self.assertNotIn("title=", html)

    def test_a_label_carries_the_tooltip_instead_of_an_icon(self):
        html = render_to_string(
            "common/tooltip.html",
            {"label": "Processed", "text": "Some help.", "classes": "tag is-light"},
        )
        self.assertIn(
            '<span class="tag is-light" data-tippy-content="Some help." tabindex="0">'
            'Processed<span class="is-sr-only">: Some help.</span></span>',
            html,
        )
        self.assertNotIn("bi-", html)

    def test_is_keyboard_focusable(self):
        html = render_to_string("common/tooltip.html", {"text": "Some help."})
        self.assertIn('tabindex="0"', html)

    def test_base_layout_loads_tippy(self):
        self.client.force_login(User.objects.create_user(username="staff@example.com"))
        html = self.client.get(reverse("home")).content.decode()
        for asset in (
            "tools/css/tippy.css",
            "tools/js/popper.min.js",
            "tools/js/tippy.umd.min.js",
            "tools/js/tooltips.js",
        ):
            with self.subTest(asset=asset):
                self.assertIn(static(asset), html)
