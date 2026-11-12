"""Houses tests for looking records up by their canonical IDs and GPM UUIDs."""

import re
import uuid

from affiliations_service.models import CDWG, Affiliation
from affiliations_service.test_api_cdwgs import ApiTestCase
from affiliations_service.test_models import make_affiliation, make_cdwg
from affiliations_service.test_users import make_user

URL = "/as/api/v1"
GPM_UUID = "6a1b5f0e-8f0c-4d7e-9a43-2b0f5d3c1e9a"


class AffiliationIdLookupTest(ApiTestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.vcep = make_affiliation(Affiliation.Type.VCEP, affiliation_id=10005)
        cls.gcep = make_affiliation(Affiliation.Type.GCEP, affiliation_id=10005)
        cls.alone = make_affiliation(Affiliation.Type.VCEP, affiliation_id=10006)

    def test_returns_both_affiliations_that_share_an_affiliation_id(self):
        body = self.get(f"{URL}/affiliations/affiliation-id/10005").json()
        self.assertEqual(
            {item["id"] for item in body}, {str(self.vcep.pk), str(self.gcep.pk)}
        )

    def test_returns_a_lone_affiliation_in_a_list(self):
        body = self.get(f"{URL}/affiliations/affiliation-id/10006").json()
        self.assertEqual([item["id"] for item in body], [str(self.alone.pk)])

    def test_includes_deleted_affiliations(self):
        self.gcep.delete()
        body = self.get(f"{URL}/affiliations/affiliation-id/10005").json()
        self.assertEqual(len(body), 2)
        self.assertEqual(sorted(item["is_deleted"] for item in body), [False, True])

    def test_returns_404_when_nothing_matches(self):
        response = self.get(f"{URL}/affiliations/affiliation-id/19999")
        self.assertEqual(response.status_code, 404)

    def test_expert_panel_id_finds_one_affiliation(self):
        body = self.get(f"{URL}/affiliations/expert-panel-id/40005").json()
        self.assertEqual(body["id"], str(self.gcep.pk))
        self.assertEqual(body["type"], "GCEP")
        response = self.get(f"{URL}/affiliations/expert-panel-id/49999")
        self.assertEqual(response.status_code, 404)

    def test_lookups_are_read_only(self):
        for path in ["affiliation-id/10005", "expert-panel-id/40005"]:
            with self.subTest(path=path):
                url = f"{URL}/affiliations/{path}"
                self.assertEqual(self.patch(url, {"full_name": "X"}).status_code, 405)
                self.assertEqual(self.delete(url).status_code, 405)


class GpmUuidLookupTest(ApiTestCase):
    def test_finds_affiliations_cdwgs_and_users_by_gpm_uuid(self):
        affiliation = make_affiliation(gpm_uuid=GPM_UUID)
        cdwg = make_cdwg("Kidney")
        cdwg.gpm_uuid = GPM_UUID
        cdwg.save()
        user = make_user(gpm_uuid=GPM_UUID)
        for resource, obj in [
            ("affiliations", affiliation),
            ("cdwgs", cdwg),
            ("users", user),
        ]:
            with self.subTest(resource=resource):
                url = f"{URL}/{resource}/gpm-uuid/{GPM_UUID}"
                self.assertEqual(self.get(url).json()["id"], str(obj.pk))
                self.assertEqual(self.patch(url, {}).status_code, 405)
                missing = f"{URL}/{resource}/gpm-uuid/{uuid.uuid4()}"
                self.assertEqual(self.get(missing).status_code, 404)


class GpmUuidInUseTest(ApiTestCase):
    def test_creating_with_a_gpm_uuid_in_use_is_refused(self):
        cdwg = make_affiliation(gpm_uuid=GPM_UUID).cdwg
        CDWG.objects.create(name="Kidney", gpm_uuid=GPM_UUID)
        make_user(gpm_uuid=GPM_UUID)
        cases = [
            (
                "affiliations",
                {"type": "GCEP", "full_name": "New", "cdwg": str(cdwg.pk)},
                "Another affiliation already has this GPM UUID.",
            ),
            ("cdwgs", {"name": "Ocular"}, "Another CDWG already has this GPM UUID."),
            (
                "users",
                {"name": "New Person", "email": "new@example.org"},
                "Another user already has this GPM UUID.",
            ),
        ]
        for resource, body, message in cases:
            with self.subTest(resource=resource):
                before = self.get(f"{URL}/{resource}").json()["count"]
                response = self.post(f"{URL}/{resource}", body | {"gpm_uuid": GPM_UUID})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {"detail": message})
                self.assertEqual(self.get(f"{URL}/{resource}").json()["count"], before)


class PathNamesTest(ApiTestCase):
    def test_records_are_addressed_by_id_and_lookups_by_their_id_names(self):
        paths = self.client.get(f"{URL}/openapi.json").json()["paths"]
        for path in [
            "/as/api/v1/affiliations/{id}",
            "/as/api/v1/cdwgs/{id}",
            "/as/api/v1/users/{id}",
            "/as/api/v1/memberships/{id}",
            "/as/api/v1/affiliations/affiliation-id/{affiliation_id}",
            "/as/api/v1/affiliations/expert-panel-id/{expert_panel_id}",
            "/as/api/v1/affiliations/gpm-uuid/{gpm_uuid}",
            "/as/api/v1/cdwgs/gpm-uuid/{gpm_uuid}",
            "/as/api/v1/users/gpm-uuid/{gpm_uuid}",
        ]:
            with self.subTest(path=path):
                self.assertIn(path, paths)


class ApiDocsWordingTest(ApiTestCase):
    def test_titles_and_summaries_capitalize_acronyms(self):
        schema = self.client.get(f"{URL}/openapi.json").content.decode()
        labels = re.findall(r'"(?:title|summary)": ?"([^"]*)"', schema)
        for word in ["Id", "Ids", "Gpm", "Uuid", "Cdwg", "Cdwgs", "Orcid", "Clinvar"]:
            with self.subTest(word=word):
                self.assertFalse(
                    [label for label in labels if re.search(rf"\b{word}\b", label)]
                )
        for label in ["Get Affiliation By GPM UUID", "Affiliation ID", "List CDWGs"]:
            with self.subTest(label=label):
                self.assertIn(label, labels)


class SchemaNamesTest(ApiTestCase):
    def test_schema_names_capitalize_cdwg(self):
        schemas = self.client.get(f"{URL}/openapi.json").json()["components"]["schemas"]
        self.assertIn("CDWGOut", schemas)
        self.assertIn("PagedCDWGOut", schemas)
        self.assertFalse([name for name in schemas if "Cdwg" in name])
