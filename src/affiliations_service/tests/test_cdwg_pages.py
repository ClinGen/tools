"""Houses tests for the CDWG pages."""

from django.test import TestCase
from django.urls import reverse

from affiliations_service.models import CDWG
from affiliations_service.tests.helpers import make_staff
from affiliations_service.tests.test_models import make_affiliation, make_cdwg


class CDWGListPageTest(TestCase):
    def setUp(self):
        self.client.force_login(make_staff("as@example.com"))

    def test_lists_cdwgs_with_affiliation_counts_and_filtered_links(self):
        cardio = make_cdwg("Cardiovascular")
        make_cdwg("Kidney")
        make_affiliation(cdwg=cardio)
        make_affiliation(cdwg=cardio)
        make_affiliation(cdwg=cardio).delete()
        response = self.client.get(reverse("as:cdwgs"))
        page = response.content.decode()
        self.assertIn("Cardiovascular", page)
        self.assertIn(f"{reverse('as:index')}?cdwg={cardio.pk}", page)
        self.assertEqual(
            [(cdwg.name, cdwg.affiliation_count) for cdwg in response.context["cdwgs"]],
            [("Cardiovascular", 2), ("Kidney", 0)],
        )

    def test_rows_link_to_their_edit_page_with_a_pencil(self):
        cdwg = make_cdwg("Kidney")
        page = self.client.get(reverse("as:cdwgs")).content.decode()
        self.assertRegex(page, r"<th[^>]*>\s*Edit\s*</th>")
        url = reverse("as:cdwg-edit", kwargs={"pk": cdwg.pk})
        link = page[
            page.index(f'href="{url}"') : page.index(
                "</a>", page.index(f'href="{url}"')
            )
        ]
        self.assertIn('aria-label="Edit Kidney"', link)
        self.assertIn("bi-pencil-square", link)
        self.assertNotIn(">Edit<", link)

    def test_the_tabs_link_to_the_cdwg_list(self):
        self.assertContains(self.client.get(reverse("as:index")), reverse("as:cdwgs"))


class CDWGFormPageTest(TestCase):
    def setUp(self):
        self.client.force_login(make_staff("as@example.com"))

    def test_create(self):
        response = self.client.post(
            reverse("as:cdwg-create"), {"name": "Kidney", "gpm_uuid": ""}
        )
        self.assertRedirects(response, reverse("as:cdwgs"))
        self.assertTrue(CDWG.objects.filter(name="Kidney").exists())

    def test_edit(self):
        cdwg = make_cdwg("Kidny")
        url = reverse("as:cdwg-edit", kwargs={"pk": cdwg.pk})
        response = self.client.post(url, {"name": "Kidney", "gpm_uuid": ""})
        self.assertRedirects(response, reverse("as:cdwgs"))
        cdwg.refresh_from_db()
        self.assertEqual(cdwg.name, "Kidney")

    def test_a_name_differing_only_in_case_shows_a_form_error(self):
        make_cdwg("Kidney")
        response = self.client.post(
            reverse("as:cdwg-create"), {"name": "KIDNEY", "gpm_uuid": ""}
        )
        self.assertContains(response, "There&#x27;s already a CDWG with this name.")
        self.assertEqual(CDWG.objects.count(), 1)

    def test_the_list_links_to_create_and_edit(self):
        cdwg = make_cdwg("Kidney")
        page = self.client.get(reverse("as:cdwgs")).content.decode()
        self.assertIn(reverse("as:cdwg-create"), page)
        self.assertIn(reverse("as:cdwg-edit", kwargs={"pk": cdwg.pk}), page)


class CDWGPermissionTest(TestCase):
    def test_cdwg_pages_require_the_as_permission(self):
        cdwg = make_cdwg()
        self.client.force_login(make_staff("no-as@example.com", as_=False))
        for url in [
            reverse("as:cdwgs"),
            reverse("as:cdwg-create"),
            reverse("as:cdwg-edit", kwargs={"pk": cdwg.pk}),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)


class CDWGSearchTest(TestCase):
    def test_q_narrows_the_cdwg_list(self):
        make_cdwg("Cardiovascular")
        make_cdwg("Kidney")
        self.client.force_login(make_staff("as@example.com"))
        page = self.client.get(reverse("as:cdwgs"), {"q": "kid"}).content.decode()
        self.assertIn("Kidney", page)
        self.assertNotIn("Cardiovascular", page)
