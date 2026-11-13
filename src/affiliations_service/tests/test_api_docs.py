"""Houses tests for the AS API's docs: paths, wording, and schema names."""

import re

from affiliations_service.tests.test_api_cdwgs import ApiTestCase


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


URL = "/as/api/v1"
