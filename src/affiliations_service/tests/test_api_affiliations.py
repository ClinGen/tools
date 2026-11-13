"""Houses tests for the AS API's affiliation endpoints."""

import uuid

from affiliations_service.models import Affiliation, ClinVarSubmitterId
from affiliations_service.tests.test_api_cdwgs import ApiTestCase
from affiliations_service.tests.test_models import make_affiliation, make_cdwg

URL = "/as/api/v1/affiliations"
GPM_UUID = "6a1b5f0e-8f0c-4d7e-9a43-2b0f5d3c1e9a"


class AffiliationListTest(ApiTestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.cardio = make_cdwg("Cardiovascular")
        cls.kidney = make_cdwg("Kidney")
        cls.vcep = make_affiliation(
            Affiliation.Type.VCEP,
            cdwg=cls.cardio,
            full_name="Cardiomyopathy VCEP",
            status=Affiliation.Status.ACTIVE,
        )
        cls.gcep = make_affiliation(
            Affiliation.Type.GCEP,
            cdwg=cls.kidney,
            full_name="Kidney Cystic GCEP",
            short_name="Cystic",
        )
        cls.deleted = make_affiliation(cdwg=cls.cardio, full_name="Gone VCEP")
        cls.deleted.delete()

    def _names(self, **params: str | int) -> list[str]:
        return [item["full_name"] for item in self.get(URL, **params).json()["items"]]

    def test_lists_affiliations_without_deleted_ones(self):
        self.assertEqual(self._names(), ["Cardiomyopathy VCEP", "Kidney Cystic GCEP"])

    def test_include_deleted_lists_deleted_ones_too(self):
        self.assertIn("Gone VCEP", self._names(include_deleted="true"))

    def test_each_filter_narrows_the_list(self):
        cases = [
            ({"type": "GCEP"}, ["Kidney Cystic GCEP"]),
            ({"status": "ACTIVE"}, ["Cardiomyopathy VCEP"]),
            ({"cdwg": str(self.kidney.pk)}, ["Kidney Cystic GCEP"]),
            ({"affiliation_id": self.vcep.affiliation_id}, ["Cardiomyopathy VCEP"]),
            ({"expert_panel_id": self.gcep.expert_panel_id}, ["Kidney Cystic GCEP"]),
            ({"q": "cystic"}, ["Kidney Cystic GCEP"]),
            ({"q": "cardio"}, ["Cardiomyopathy VCEP"]),
        ]
        for params, expected in cases:
            with self.subTest(params=params):
                self.assertEqual(self._names(**params), expected)

    def test_items_include_the_cdwg_and_submitter_ids(self):
        ClinVarSubmitterId.objects.create(affiliation=self.vcep, submitter_id="500001")
        item = self.get(URL, type="VCEP").json()["items"][0]
        self.assertEqual(item["cdwg"]["name"], "Cardiovascular")
        self.assertEqual(item["clinvar_submitter_ids"], ["500001"])
        self.assertEqual(item["id"], str(self.vcep.pk))


class AffiliationCreateTest(ApiTestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.cardio = make_cdwg("Cardiovascular")

    def _body(self, **fields: object) -> dict:
        return {
            "type": "GCEP",
            "full_name": "Hypertrophic Cardiomyopathy GCEP",
            "cdwg": str(self.cardio.pk),
            "gpm_uuid": GPM_UUID,
            "clinvar_submitter_ids": ["500001", "500002"],
        } | fields

    def test_create_assigns_ids(self):
        response = self.post(URL, self._body())
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(
            (body["affiliation_id"], body["expert_panel_id"]), (10000, 40000)
        )
        self.assertEqual(body["status"], "APPLYING")
        self.assertEqual(body["clinvar_submitter_ids"], ["500001", "500002"])

    def test_client_supplied_ids_are_rejected(self):
        for field in ["affiliation_id", "expert_panel_id"]:
            with self.subTest(field=field):
                response = self.post(URL, self._body(**{field: 10500}))
                self.assertEqual(response.status_code, 422)
        self.assertFalse(Affiliation.objects.exists())

    def test_broken_rules_return_400(self):
        somatic = make_cdwg("Somatic Cancer")
        none = make_cdwg("None")
        sc_vcep_outside_somatic = self._body(type="SC_VCEP")
        independent_with_gpm_uuid = self._body(
            type="INDEPENDENT_CURATION", cdwg=str(none.pk)
        )
        good_sc_vcep = self._body(type="SC_VCEP", cdwg=str(somatic.pk))
        self.assertEqual(self.post(URL, sc_vcep_outside_somatic).status_code, 400)
        self.assertEqual(self.post(URL, independent_with_gpm_uuid).status_code, 400)
        self.assertEqual(self.post(URL, good_sc_vcep).status_code, 201)

    def test_unknown_cdwg_returns_400(self):
        response = self.post(URL, self._body(cdwg=str(uuid.uuid4())))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "There's no CDWG with that ID."})


class AffiliationUpdateTest(ApiTestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.cardio = make_cdwg("Cardiovascular")
        cls.affiliation = make_affiliation(Affiliation.Type.GCEP, cdwg=cls.cardio)
        ClinVarSubmitterId.objects.create(affiliation=cls.affiliation, submitter_id="1")

    def _url(self) -> str:
        return f"{URL}/{self.affiliation.pk}"

    def test_get(self):
        body = self.get(self._url()).json()
        self.assertEqual(body["expert_panel_id"], 40000)
        self.assertFalse(body["is_deleted"])

    def test_patch_changes_fields_and_replaces_submitter_ids(self):
        kidney = make_cdwg("Kidney")
        response = self.patch(
            self._url(),
            {
                "full_name": "Renamed GCEP",
                "status": "ACTIVE",
                "cdwg": str(kidney.pk),
                "clinvar_submitter_ids": ["2", "3"],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.affiliation.refresh_from_db()
        self.assertEqual(self.affiliation.full_name, "Renamed GCEP")
        self.assertEqual(self.affiliation.cdwg, kidney)
        submitter_ids = self.affiliation.clinvar_submitter_ids.values_list(  # type: ignore
            "submitter_id", flat=True
        )
        self.assertEqual(list(submitter_ids), ["2", "3"])

    def test_patch_leaves_out_fields_unchanged(self):
        self.patch(self._url(), {"short_name": "Short"})
        self.affiliation.refresh_from_db()
        self.assertEqual(self.affiliation.clinvar_submitter_ids.count(), 1)  # type: ignore
        self.assertEqual(self.affiliation.short_name, "Short")

    def test_patching_a_locked_field_returns_400(self):
        cases = {
            "affiliation_id": 10500,
            "expert_panel_id": 40500,
            "type": "VCEP",
            "gpm_uuid": GPM_UUID,
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                response = self.patch(self._url(), {field: value})
                self.assertEqual(response.status_code, 400)
        self.affiliation.refresh_from_db()
        self.assertEqual(self.affiliation.type, Affiliation.Type.GCEP)

    def test_patching_a_locked_field_to_its_current_value_is_fine(self):
        response = self.patch(self._url(), {"type": "GCEP", "affiliation_id": 10000})
        self.assertEqual(response.status_code, 200)

    def test_delete_soft_deletes(self):
        response = self.delete(self._url())
        self.assertEqual(response.status_code, 204)
        self.affiliation.refresh_from_db()
        self.assertTrue(self.affiliation.is_deleted)

    def test_unknown_ids_return_404(self):
        unknown = f"{URL}/{uuid.uuid4()}"
        self.assertEqual(self.get(unknown).status_code, 404)
        self.assertEqual(self.patch(unknown, {"full_name": "X"}).status_code, 404)
        self.assertEqual(self.delete(unknown).status_code, 404)

    def test_requests_without_a_key_get_401(self):
        self.assertEqual(self.client.get(URL).status_code, 401)
