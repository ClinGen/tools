"""Houses tests for the Add Another rows on the AS's forms."""

from django.test import TestCase
from django.urls import reverse

from affiliations_service.models import Affiliation
from affiliations_service.tests.helpers import make_staff
from affiliations_service.tests.test_affiliation_forms import formset_data
from affiliations_service.tests.test_models import make_cdwg


class AddAnotherRowTest(TestCase):
    def setUp(self):
        self.client.force_login(make_staff("as@example.com"))

    def test_posting_two_new_submitter_ids_saves_both(self):
        cdwg = make_cdwg("Cardiovascular")
        data = {
            "type": "VCEP",
            "full_name": "Two IDs VCEP",
            "short_name": "",
            "status": "APPLYING",
            "cdwg": str(cdwg.pk),
            "gpm_uuid": "",
        } | formset_data("500001", "500002")
        self.client.post(reverse("as:affiliation-create"), data)
        affiliation = Affiliation.objects.get()
        submitter_ids = affiliation.clinvar_submitter_ids.values_list(
            "submitter_id", flat=True
        )
        self.assertEqual(list(submitter_ids), ["500001", "500002"])

    def test_forms_offer_to_add_another_row(self):
        cases = [
            (reverse("as:affiliation-create"), "clinvar_submitter_ids"),
            (reverse("as:user-create"), "other_emails"),
        ]
        for url, prefix in cases:
            with self.subTest(url=url):
                page = self.client.get(url).content.decode()
                self.assertIn(f'data-formset-add="{prefix}"', page)
                self.assertIn(f'id="{prefix}-empty-form"', page)
                # Space between the last row and the Add Another button.
                self.assertIn(f'id="{prefix}-rows" class="mb-4"', page)
                self.assertIn("affiliations_service/formset.js", page)
                self.assertNotIn("save, then edit", page)
