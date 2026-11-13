"""Houses tests for the shared breadcrumbs."""

from django.template.loader import render_to_string
from django.test import TestCase
from django.urls import reverse

from common import breadcrumbs


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
