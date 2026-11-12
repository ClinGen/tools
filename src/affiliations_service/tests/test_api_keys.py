"""Houses tests for the AS's API keys and API authentication."""

import hashlib

from django.test import TestCase

from affiliations_service.models import ApiKey

CDWGS_URL = "/as/api/v1/cdwgs"


class ApiKeyModelTest(TestCase):
    def test_creating_a_key_stores_only_its_hash_and_prefix(self):
        api_key, raw_key = ApiKey.objects.create_key(name="GCI")
        self.assertTrue(raw_key.startswith("as_"))
        self.assertEqual(api_key.prefix, raw_key[:8])
        self.assertEqual(api_key.key_hash, hashlib.sha256(raw_key.encode()).hexdigest())
        stored = [str(value) for value in ApiKey.objects.values().first().values()]  # type: ignore
        self.assertNotIn(raw_key, stored)

    def test_verify_finds_only_active_keys(self):
        api_key, raw_key = ApiKey.objects.create_key(name="GCI")
        self.assertEqual(ApiKey.objects.verify(raw_key), api_key)
        self.assertIsNone(ApiKey.objects.verify("as_wrong"))
        self.assertIsNone(ApiKey.objects.verify(""))
        api_key.is_active = False
        api_key.save()
        self.assertIsNone(ApiKey.objects.verify(raw_key))


class ApiAuthTest(TestCase):
    def test_requests_without_a_good_key_get_401(self):
        inactive, inactive_raw = ApiKey.objects.create_key(name="Old")
        inactive.is_active = False
        inactive.save()
        for label, headers in [
            ("no key", {}),
            ("unknown key", {"X-Api-Key": "as_unknown"}),
            ("inactive key", {"X-Api-Key": inactive_raw}),
        ]:
            with self.subTest(label):
                response = self.client.get(CDWGS_URL, headers=headers)
                self.assertEqual(response.status_code, 401)

    def test_an_active_key_works_and_records_its_use(self):
        api_key, raw_key = ApiKey.objects.create_key(name="GCI")
        response = self.client.get(CDWGS_URL, headers={"X-Api-Key": raw_key})
        self.assertEqual(response.status_code, 200)
        api_key.refresh_from_db()
        self.assertIsNotNone(api_key.last_used_at)
        self.assertEqual(api_key.history.count(), 1)  # type: ignore

    def test_the_docs_load_without_a_key(self):
        self.assertEqual(self.client.get("/as/api/v1/docs").status_code, 200)
        self.assertEqual(self.client.get("/as/api/v1/openapi.json").status_code, 200)
