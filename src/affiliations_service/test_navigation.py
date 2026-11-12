"""Houses tests for the AS's navbar and breadcrumbs."""

from django.test import TestCase
from django.urls import reverse

from affiliations_service.test_models import make_affiliation, make_cdwg
from affiliations_service.test_people import make_person
from affiliations_service.tests import make_user

NAVBAR_URLS = [
    "as:index",
    "as:affiliation-create",
    "as:people",
    "as:person-create",
    "as:cdwgs",
    "as:cdwg-create",
]


class NavbarTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.affiliation = make_affiliation()
        cls.person = make_person()

    def setUp(self):
        self.client.force_login(make_user("as@example.com"))

    def _pages(self) -> list[str]:
        affiliation, person, cdwg = self.affiliation, self.person, self.affiliation.cdwg
        return [
            *[reverse(name) for name in NAVBAR_URLS],
            affiliation.get_absolute_url(),
            reverse("as:affiliation-edit", kwargs={"pk": affiliation.pk}),
            reverse("as:affiliation-delete", kwargs={"pk": affiliation.pk}),
            person.get_absolute_url(),
            reverse("as:person-edit", kwargs={"pk": person.pk}),
            reverse("as:cdwg-edit", kwargs={"pk": cdwg.pk}),
        ]

    def test_every_page_links_to_search_and_add_for_each_resource(self):
        for page_url in self._pages():
            page = self.client.get(page_url).content.decode()
            for name in NAVBAR_URLS:
                with self.subTest(page=page_url, link=name):
                    self.assertIn(f'href="{reverse(name)}"', page)

    def test_the_navbar_comes_after_the_title_and_has_no_tabs(self):
        page = self.client.get(reverse("as:index")).content.decode()
        self.assertLess(page.index('class="subtitle"'), page.index('id="as-navbar"'))
        self.assertNotIn('class="tabs', page)

    def test_the_current_pages_link_is_bold(self):
        page = self.client.get(reverse("as:people")).content.decode()
        self.assertIn(
            f'href="{reverse("as:people")}" class="navbar-item has-text-weight-bold"',
            page,
        )
        self.assertIn(f'href="{reverse("as:cdwgs")}" class="navbar-item"', page)


class CdwgSearchTest(TestCase):
    def test_q_narrows_the_cdwg_list(self):
        make_cdwg("Cardiovascular")
        make_cdwg("Kidney")
        self.client.force_login(make_user("as@example.com"))
        page = self.client.get(reverse("as:cdwgs"), {"q": "kid"}).content.decode()
        self.assertIn("Kidney", page)
        self.assertNotIn("Cardiovascular", page)


class BreadcrumbTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.affiliation = make_affiliation(full_name="Kidney Cystic GCEP")
        cls.person = make_person(name="Ada Lovelace")

    def setUp(self):
        self.client.force_login(make_user("as@example.com"))

    def _crumbs(self, url: str) -> list[tuple[str, str]]:
        """Returns each breadcrumb's text and link on a page."""
        crumbs = self.client.get(url).context["breadcrumbs"]
        return [(crumb.text, crumb.url) for crumb in crumbs]

    def test_edit_page_trail(self):
        affiliation = self.affiliation
        edit_url = reverse("as:affiliation-edit", kwargs={"pk": affiliation.pk})
        self.assertEqual(
            self._crumbs(edit_url),
            [
                ("Affiliation Search", reverse("as:index")),
                ("Kidney Cystic GCEP", affiliation.get_absolute_url()),
                ("Edit", ""),
            ],
        )

    def test_list_pages_end_at_their_search_crumb(self):
        cases = [
            ("as:index", "Affiliation Search"),
            ("as:people", "People Search"),
            ("as:cdwgs", "CDWG Search"),
        ]
        for name, text in cases:
            with self.subTest(page=name):
                self.assertEqual(self._crumbs(reverse(name))[-1], (text, ""))

    def test_person_and_new_pages_trails(self):
        self.assertEqual(
            [text for text, _ in self._crumbs(self.person.get_absolute_url())],
            ["People Search", "Ada Lovelace"],
        )
        self.assertEqual(
            [text for text, _ in self._crumbs(reverse("as:affiliation-create"))],
            ["Affiliation Search", "New Affiliation"],
        )

    def test_the_breadcrumbs_render_with_the_last_one_active(self):
        page = self.client.get(self.affiliation.get_absolute_url()).content.decode()
        self.assertIn('class="breadcrumb"', page)
        self.assertNotIn(
            '<i class="bi bi-house', page[page.index('class="breadcrumb"') :]
        )
        self.assertIn('<li class="is-active">', page)
