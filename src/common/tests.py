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
from common import breadcrumbs
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
            '<span class="tag is-light" data-tippy-content="Some help." tabindex="0" '
            'style="cursor: default">'
            'Processed<span class="is-sr-only">: Some help.</span></span>',
            html,
        )
        self.assertNotIn("bi-", html)

    def test_a_label_with_an_href_is_a_link(self):
        html = render_to_string(
            "common/tooltip.html",
            {"label": "Processed", "text": "Some help.", "href": "?status=x"},
        )
        self.assertIn(
            '<a href="?status=x" data-tippy-content="Some help.">Processed'
            '<span class="is-sr-only">: Some help.</span></a>',
            html,
        )
        self.assertNotIn("cursor: default", html)

    def test_keeps_the_arrow_cursor(self):
        for context in ({"icon_name": "info-circle"}, {"label": "Processed"}):
            with self.subTest(context=context):
                html = render_to_string(
                    "common/tooltip.html", {"text": "Some help.", **context}
                )
                self.assertIn('style="cursor: default"', html)

    def test_is_keyboard_focusable(self):
        html = render_to_string("common/tooltip.html", {"text": "Some help."})
        self.assertIn('tabindex="0"', html)

    def test_base_layout_loads_tippy(self):
        self.client.force_login(User.objects.create_user(username="staff@example.com"))
        html = self.client.get(reverse("home")).content.decode()
        for asset in (
            "tools/css/tippy.css",
            "tools/css/custom.css",
            "tools/js/popper.min.js",
            "tools/js/tippy.umd.min.js",
            "tools/js/tooltips.js",
        ):
            with self.subTest(asset=asset):
                self.assertIn(static(asset), html)


class ConfirmModalTest(TestCase):
    def test_every_page_has_the_modal_and_its_script(self):
        response = self.client.get(reverse("home"))
        self.assertTemplateUsed(response, "common/confirm_modal.html")
        self.assertContains(response, 'id="confirm-modal"')
        self.assertContains(response, static("tools/js/confirm-modal.js"))

    def test_no_template_asks_with_window_confirm(self):
        templates = settings.BASE_DIR.glob("**/templates/**/*.html")
        for template in templates:
            with self.subTest(str(template.relative_to(settings.BASE_DIR))):
                self.assertNotIn("confirm(", template.read_text())


class BreadcrumbsTest(TestCase):
    def test_section_links_to_its_list_unless_it_is_the_current_page(self):
        self.assertEqual(
            breadcrumbs.section("Records", "css:records", "list-ul"),
            breadcrumbs.Crumb("Records", reverse("css:records"), "list-ul"),
        )
        self.assertEqual(
            breadcrumbs.section("Records", "css:records", current=True).url, ""
        )

    def test_section_defaults_to_the_search_icon(self):
        self.assertEqual(breadcrumbs.section("CDWG Search", "as:cdwgs").icon, "search")

    def test_action_is_the_current_page(self):
        self.assertEqual(
            breadcrumbs.action("New Batch", "plus-circle"),
            breadcrumbs.Crumb("New Batch", "", "plus-circle"),
        )

    def test_partial_links_every_crumb_but_the_last(self):
        html = render_to_string(
            "common/breadcrumbs.html",
            {
                "breadcrumbs": [
                    breadcrumbs.section("Records", "css:records", "list-ul"),
                    breadcrumbs.action("New Batch", "plus-circle"),
                ]
            },
        )
        self.assertIn(f'<a href="{reverse("css:records")}">', html)
        self.assertInHTML(
            '<li class="is-active"><b><a href="" aria-current="page">'
            '<i class="bi bi-plus-circle mr-2"></i>New Batch</a></b></li>',
            html,
        )

    def test_partial_renders_nothing_without_a_trail(self):
        self.assertEqual(render_to_string("common/breadcrumbs.html", {}).strip(), "")
