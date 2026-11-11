"""Houses tests for the AS API's CDWG endpoints."""

import uuid
from typing import TYPE_CHECKING

from django.test import TestCase

from affiliations_service.models import CDWG, ApiKey

if TYPE_CHECKING:
    # Django's stubs name the test client's response type only for type checkers.
    from django.test.client import _MonkeyPatchedWSGIResponse as Response  # ruff: ignore[import-private-name]

URL = "/as/api/v1/cdwgs"
GPM_UUID = "6a1b5f0e-8f0c-4d7e-9a43-2b0f5d3c1e9a"


class ApiTestCase(TestCase):
    """Sends every request with an active API key."""

    def setUp(self):
        _, raw_key = ApiKey.objects.create_key(name="Test Client")
        self.headers = {"X-Api-Key": raw_key}

    def get(self, url: str, **params: str | int) -> "Response":
        return self.client.get(url, params, headers=self.headers)

    def post(self, url: str, data: dict) -> "Response":
        return self.client.post(
            url, data, content_type="application/json", headers=self.headers
        )

    def patch(self, url: str, data: dict) -> "Response":
        return self.client.patch(
            url, data, content_type="application/json", headers=self.headers
        )

    def delete(self, url: str) -> "Response":
        return self.client.delete(url, headers=self.headers)


class CdwgApiTest(ApiTestCase):
    def test_list_is_paginated(self):
        CDWG.objects.create(name="Kidney")
        CDWG.objects.create(name="Cardiovascular")
        body = self.get(URL, limit=1).json()
        self.assertEqual(body["count"], 2)
        self.assertEqual([item["name"] for item in body["items"]], ["Cardiovascular"])

    def test_get(self):
        cdwg = CDWG.objects.create(name="Kidney", gpm_uuid=GPM_UUID)
        body = self.get(f"{URL}/{cdwg.pk}").json()
        self.assertEqual(
            body, {"id": str(cdwg.pk), "name": "Kidney", "gpm_uuid": GPM_UUID}
        )

    def test_create(self):
        response = self.post(URL, {"name": "Kidney", "gpm_uuid": GPM_UUID})
        self.assertEqual(response.status_code, 201)
        cdwg = CDWG.objects.get()
        self.assertEqual(response.json()["id"], str(cdwg.pk))
        self.assertEqual(str(cdwg.gpm_uuid), GPM_UUID)

    def test_update(self):
        cdwg = CDWG.objects.create(name="Kidny")
        response = self.patch(f"{URL}/{cdwg.pk}", {"name": "Kidney"})
        self.assertEqual(response.status_code, 200)
        cdwg.refresh_from_db()
        self.assertEqual(cdwg.name, "Kidney")
        self.assertIsNone(cdwg.gpm_uuid)

    def test_duplicate_name_returns_400(self):
        CDWG.objects.create(name="Kidney")
        response = self.post(URL, {"name": "KIDNEY"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"detail": "There's already a CDWG with this name."}
        )

    def test_missing_name_returns_422(self):
        self.assertEqual(self.post(URL, {}).status_code, 422)

    def test_unknown_id_returns_404(self):
        self.assertEqual(self.get(f"{URL}/{uuid.uuid4()}").status_code, 404)
        self.assertEqual(
            self.patch(f"{URL}/{uuid.uuid4()}", {"name": "X"}).status_code, 404
        )
