"""Houses tests for the shared templates: tooltips and the confirmation modal."""

from django.conf import settings
from django.contrib.auth.models import User
from django.template.loader import render_to_string
from django.templatetags.static import static
from django.test import TestCase
from django.urls import reverse


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
