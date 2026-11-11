"""Houses tests for creating, editing, and deleting affiliations in the UI."""

from typing import TYPE_CHECKING

from django.test import TestCase
from django.urls import reverse

from affiliations_service.models import Affiliation, ClinVarSubmitterId
from affiliations_service.test_models import make_affiliation, make_cdwg
from affiliations_service.tests import make_user

if TYPE_CHECKING:
    # Django's stubs name the test client's response type only for type checkers.
    from django.test.client import _MonkeyPatchedWSGIResponse as Response  # ruff: ignore[import-private-name]

GPM_UUID = "6a1b5f0e-8f0c-4d7e-9a43-2b0f5d3c1e9a"


def formset_data(
    *submitter_ids: str, existing: tuple[ClinVarSubmitterId, ...] = ()
) -> dict:
    """Returns POST data for the ClinVar submitter ID formset.

    Args:
        *submitter_ids: New submitter IDs to add.
        existing: Saved submitter IDs to keep, in the formset's first rows.

    Returns:
        The management form and one row per submitter ID.
    """
    prefix = "clinvar_submitter_ids"
    rows = [(str(item.pk), item.submitter_id) for item in existing]
    rows += [("", submitter_id) for submitter_id in submitter_ids]
    data = {
        f"{prefix}-TOTAL_FORMS": str(len(rows)),
        f"{prefix}-INITIAL_FORMS": str(len(existing)),
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }
    for index, (pk, submitter_id) in enumerate(rows):
        data[f"{prefix}-{index}-id"] = pk
        data[f"{prefix}-{index}-submitter_id"] = submitter_id
    return data


class AffiliationCreatePageTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.cardio = make_cdwg("Cardiovascular")

    def setUp(self):
        self.client.force_login(make_user("as@example.com"))

    def _post(self, **fields: str) -> "Response":
        data = {
            "type": "GCEP",
            "full_name": "Hypertrophic Cardiomyopathy GCEP",
            "short_name": "HCM",
            "status": "APPLYING",
            "cdwg": str(self.cardio.pk),
            "gpm_uuid": "",
        } | fields
        return self.client.post(
            reverse("as:affiliation-create"), data | formset_data("500001")
        )

    def test_create_assigns_ids_and_redirects_to_the_page(self):
        response = self._post()
        affiliation = Affiliation.objects.get()
        self.assertRedirects(response, affiliation.get_absolute_url())
        self.assertEqual(
            (affiliation.affiliation_id, affiliation.expert_panel_id), (10000, 40000)
        )
        submitter_ids = affiliation.clinvar_submitter_ids.values_list(
            "submitter_id", flat=True
        )
        self.assertEqual(list(submitter_ids), ["500001"])

    def test_a_broken_rule_shows_a_plain_error(self):
        response = self._post(type="SC_VCEP")
        self.assertContains(response, "An SC-VCEP must be in the Somatic Cancer CDWG.")
        self.assertFalse(Affiliation.objects.exists())

    def test_the_list_links_to_the_create_page(self):
        response = self.client.get(reverse("as:index"))
        self.assertContains(response, reverse("as:affiliation-create"))


class AffiliationEditPageTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.cardio = make_cdwg("Cardiovascular")
        cls.affiliation = make_affiliation(Affiliation.Type.GCEP, cdwg=cls.cardio)
        cls.submitter = ClinVarSubmitterId.objects.create(
            affiliation=cls.affiliation, submitter_id="500001"
        )

    def setUp(self):
        self.client.force_login(make_user("as@example.com"))
        self.url = reverse("as:affiliation-edit", kwargs={"pk": self.affiliation.pk})

    def _post(self, formset: dict | None = None, **fields: str) -> "Response":
        data = {
            "full_name": "Renamed GCEP",
            "short_name": "",
            "status": "ACTIVE",
            "cdwg": str(self.cardio.pk),
        } | fields
        formset = formset or formset_data(existing=(self.submitter,))
        return self.client.post(self.url, data | formset)

    def test_edit_saves_and_redirects(self):
        response = self._post()
        self.assertRedirects(response, self.affiliation.get_absolute_url())
        self.affiliation.refresh_from_db()
        self.assertEqual(self.affiliation.full_name, "Renamed GCEP")
        self.assertEqual(self.affiliation.status, Affiliation.Status.ACTIVE)

    def test_locked_fields_are_shown_read_only_and_cant_change(self):
        page = self.client.get(self.url).content.decode()
        for field in ["affiliation_id", "expert_panel_id", "type", "gpm_uuid"]:
            with self.subTest(field=field):
                self.assertNotIn(f'name="{field}"', page)
        self.assertIn("40000", page)
        self._post(
            type="VCEP",
            affiliation_id="10500",
            expert_panel_id="50500",
            gpm_uuid=GPM_UUID,
        )
        self.affiliation.refresh_from_db()
        self.assertEqual(self.affiliation.type, Affiliation.Type.GCEP)
        self.assertEqual(self.affiliation.affiliation_id, 10000)
        self.assertIsNone(self.affiliation.gpm_uuid)

    def test_submitter_ids_can_be_added_and_removed(self):
        formset = formset_data("500002", existing=(self.submitter,))
        formset["clinvar_submitter_ids-0-DELETE"] = "on"
        self._post(formset)
        submitter_ids = self.affiliation.clinvar_submitter_ids.values_list(  # type: ignore
            "submitter_id", flat=True
        )
        self.assertEqual(list(submitter_ids), ["500002"])

    def test_the_affiliation_page_links_to_edit_and_delete(self):
        page = self.client.get(self.affiliation.get_absolute_url()).content.decode()
        self.assertIn(self.url, page)
        self.assertIn(
            reverse("as:affiliation-delete", kwargs={"pk": self.affiliation.pk}), page
        )


class AffiliationDeletePageTest(TestCase):
    def setUp(self):
        self.client.force_login(make_user("as@example.com"))
        self.affiliation = make_affiliation(full_name="Doomed VCEP")
        self.url = reverse("as:affiliation-delete", kwargs={"pk": self.affiliation.pk})

    def test_get_asks_for_confirmation(self):
        response = self.client.get(self.url)
        self.assertContains(response, "Delete Doomed VCEP?")
        self.affiliation.refresh_from_db()
        self.assertFalse(self.affiliation.is_deleted)

    def test_post_soft_deletes_and_leaves_the_list(self):
        response = self.client.post(self.url)
        self.assertRedirects(response, reverse("as:index"))
        self.affiliation.refresh_from_db()
        self.assertTrue(self.affiliation.is_deleted)
        self.assertNotContains(self.client.get(reverse("as:index")), "Doomed VCEP")


class FormPermissionTest(TestCase):
    def test_form_pages_require_the_as_permission(self):
        affiliation = make_affiliation()
        urls = [
            reverse("as:affiliation-create"),
            reverse("as:affiliation-edit", kwargs={"pk": affiliation.pk}),
            reverse("as:affiliation-delete", kwargs={"pk": affiliation.pk}),
        ]
        self.client.force_login(make_user("no-as@example.com", as_=False))
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
                self.assertEqual(self.client.post(url).status_code, 403)
