"""Houses tests for looking affiliations up by affiliation ID and expert panel ID."""

from affiliations_service.models import Affiliation
from affiliations_service.tests.test_api_cdwgs import ApiTestCase
from affiliations_service.tests.test_models import make_affiliation

URL = "/as/api/v1"


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
