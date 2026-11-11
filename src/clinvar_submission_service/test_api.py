import json
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.urls import reverse

from clinvar_submission_service.api_auth import API_KEY_HEADER
from clinvar_submission_service.clients import ClinVarError
from clinvar_submission_service.content import Affiliation
from clinvar_submission_service.fakes import (
    FakeClinVarClient,
    make_content,
    make_record,
)
from clinvar_submission_service.models import ApiKey, Batch, Record
from clinvar_submission_service.services import forward_batch, save_batch
from common.models import make_slug

CONTENT = make_content()

AFFILIATION = {"id": 10007, "name": "Hearing Loss VCEP"}

SUBMISSIONS_URL = "/css/api/v1/submissions"

RECORDS_URL = "/css/api/v1/records"


class ApiTestCase(TestCase):
    def setUp(self):
        self.fake = FakeClinVarClient()
        patcher = mock.patch(
            "clinvar_submission_service.services.ClinVarClient.from_settings",
            return_value=self.fake,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.api_key, self.raw_key = ApiKey.objects.create_key(name="GCI")

    def post_record(self, record: object, raw_key: str | None = None):
        # Wraps the record with the test affiliation.
        return self.post_body(
            {"affiliation": AFFILIATION, "record": record}, raw_key=raw_key
        )

    def post_body(self, body: object, raw_key: str | None = None):
        return self.client.post(
            RECORDS_URL,
            body,
            content_type="application/json",
            headers={API_KEY_HEADER: raw_key or self.raw_key},
        )

    def _saved(self) -> Batch:
        """Returns a batch of CONTENT's records, saved but not yet sent."""
        return save_batch(
            api_key=self.api_key,
            affiliation=Affiliation.model_validate(AFFILIATION),
            payload=CONTENT,
        )

    def get(self, url: str, raw_key: str | None = None):
        return self.client.get(url, headers={API_KEY_HEADER: raw_key or self.raw_key})


class ForwardSubmissionTest(ApiTestCase):
    def test_a_batch_clinvar_accepts_is_submitted(self):
        batch = self._saved()
        forward_batch(batch)
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.SUBMITTED_TO_CLINVAR)
        self.assertEqual(batch.clinvar_submission_id, "SUB000001")
        self.assertIsNotNone(batch.next_poll_at)
        self.assertEqual(self.fake.submitted, [CONTENT])

    def test_a_batch_clinvar_rejects_is_send_failed(self):
        self.fake.submit_error = ClinVarError("ClinVar returned 400", retryable=False)
        batch = self._saved()
        forward_batch(batch)
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.SEND_TO_CLINVAR_FAILED)
        self.assertEqual(batch.error_message, "ClinVar returned 400")
        self.assertEqual(batch.clinvar_submission_id, "")

    def test_a_failed_send_is_not_retried(self):
        self.fake.submit_error = ClinVarError("ClinVar returned 503", retryable=True)
        with mock.patch.object(self.fake, "submit", wraps=self.fake.submit) as submit:
            forward_batch(self._saved())
        submit.assert_called_once()

    def test_an_unconfigured_client_is_send_failed(self):
        batch = self._saved()
        with mock.patch(
            "clinvar_submission_service.services.ClinVarClient.from_settings",
            side_effect=ImproperlyConfigured("Set CSS_CLINVAR_API_KEY."),
        ):
            forward_batch(batch)
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.SEND_TO_CLINVAR_FAILED)


class CreateRecordTest(ApiTestCase):
    def test_posting_a_record_creates_a_waiting_record(self):
        record = make_record("var-1")
        response = self.post_record(record)
        self.assertEqual(response.status_code, 201)
        saved = Record.objects.get()
        self.assertEqual(saved.status, Record.Status.WAITING_FOR_BATCH)
        self.assertEqual(saved.payload, record)
        self.assertEqual(saved.slug, make_slug("R", saved.pk))
        self.assertEqual(saved.api_key, self.api_key)
        self.assertEqual(saved.affiliation_id, AFFILIATION["id"])
        self.assertEqual(saved.affiliation_name, AFFILIATION["name"])
        self.assertFalse(Batch.objects.exists())
        self.assertEqual(self.fake.submitted, [])
        body = json.loads(response.content)
        self.assertEqual(body["slug"], saved.slug)
        self.assertEqual(body["status"], "waiting_for_batch")
        self.assertEqual(body["affiliation"], AFFILIATION)
        self.assertEqual(body["record"], record)

    def test_saves_the_records_fields(self):
        self.post_record(
            make_record("var-2", recordStatus="update", clinvarAccession="SCV000000002")
        )
        record = Record.objects.get()
        self.assertEqual(record.local_id, "var-2")
        self.assertEqual(record.hgvs, "NC_000017.11:g.43045712T>C")
        self.assertEqual(record.gene_symbol, "BRCA1")
        self.assertEqual(record.condition_id, "MONDO:0011450")
        self.assertEqual(record.classification, "Likely pathogenic")
        self.assertEqual(record.mode_of_inheritance, "Autosomal dominant inheritance")
        self.assertEqual(record.date_last_evaluated.isoformat(), "2026-10-01")
        self.assertEqual(record.collection_method, "curation")
        self.assertEqual(record.record_status, "update")
        self.assertEqual(record.clinvar_accession, "SCV000000002")
        self.assertEqual(record.history.count(), 1)  # type: ignore

    def test_reposting_a_waiting_record_replaces_it_and_keeps_history(self):
        first = json.loads(self.post_record(make_record("var-1")).content)
        changed = make_record(
            "var-1",
            germlineClassification={"germlineClassificationDescription": "Pathogenic"},
        )
        response = self.post_record(changed)
        self.assertEqual(response.status_code, 200)
        record = Record.objects.get()
        self.assertEqual(json.loads(response.content)["slug"], first["slug"])
        self.assertEqual(record.payload, changed)
        self.assertEqual(record.classification, "Pathogenic")
        self.assertEqual(record.mode_of_inheritance, "")
        self.assertEqual(record.history.count(), 2)  # type: ignore
        oldest = record.history.earliest()  # type: ignore
        self.assertEqual(oldest.classification, "Likely pathogenic")

    def test_reposting_after_the_record_is_batched_makes_a_new_record(self):
        self.post_record(make_record("var-1"))
        Record.objects.update(status=Record.Status.IN_BATCH)
        response = self.post_record(make_record("var-1"))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Record.objects.count(), 2)
        self.assertEqual(
            Record.objects.filter(status=Record.Status.WAITING_FOR_BATCH).count(), 1
        )

    def test_the_same_local_id_from_another_affiliation_is_a_new_record(self):
        self.post_record(make_record("var-1"))
        other = {"id": 10008, "name": "Cardiomyopathy VCEP"}
        response = self.post_body(
            {"affiliation": other, "record": make_record("var-1")}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Record.objects.count(), 2)

    def test_records_without_a_local_id_are_never_replaced(self):
        record = make_record()
        del record["localID"]
        self.post_record(record)
        self.assertEqual(self.post_record(record).status_code, 201)
        self.assertEqual(Record.objects.count(), 2)

    def test_rejects_a_bad_record_and_saves_nothing(self):
        cases = {
            "unknown field": make_record(unknownField="x"),
            "bad classification": make_record(
                germlineClassification={
                    "germlineClassificationDescription": "Probably fine"
                }
            ),
            "update without an accession": make_record(recordStatus="update"),
            "two conditions": make_record(
                conditionSet={
                    "condition": [
                        {"db": "MONDO", "id": "MONDO:0011450"},
                        {"db": "MONDO", "id": "MONDO:0007254"},
                    ]
                }
            ),
            "content in place of a record": make_content(),
        }
        for name, record in cases.items():
            with self.subTest(name):
                self.assertEqual(self.post_record(record).status_code, 422)
        self.assertFalse(Record.objects.exists())

    def test_rejects_a_missing_or_bad_affiliation_or_extra_fields(self):
        record = make_record()
        cases = {
            "not an object": ["not", "an", "object"],
            "record only": record,
            "no affiliation": {"record": record},
            "non-integer ID": {
                "affiliation": {"id": "VCEP", "name": "Hearing Loss VCEP"},
                "record": record,
            },
            "empty name": {"affiliation": {"id": 10007, "name": ""}, "record": record},
            "submission-level field": {
                "affiliation": AFFILIATION,
                "record": record,
                "assertionCriteria": {"db": "PubMed", "id": "25741868"},
            },
        }
        for name, body in cases.items():
            with self.subTest(name):
                self.assertEqual(self.post_body(body).status_code, 422)
        self.assertFalse(Record.objects.exists())

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=100)
    def test_rejects_a_body_over_the_upload_limit(self):
        self.assertEqual(self.post_record(make_record()).status_code, 400)
        self.assertFalse(Record.objects.exists())


class ReadRecordTest(ApiTestCase):
    def test_returns_the_clients_record(self):
        slug = json.loads(self.post_record(make_record("var-1")).content)["slug"]
        Record.objects.update(clinvar_accession="SCV000000009")
        response = self.get(f"{RECORDS_URL}/{slug}")
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["status"], "waiting_for_batch")
        self.assertEqual(body["clinvar_accession"], "SCV000000009")
        self.assertEqual(body["local_id"], "var-1")
        self.assertEqual(body["record"], make_record("var-1"))

    def test_another_clients_record_is_not_found(self):
        _, other_raw = ApiKey.objects.create_key(name="VCI")
        slug = json.loads(self.post_record(make_record(), raw_key=other_raw).content)[
            "slug"
        ]
        self.assertEqual(self.get(f"{RECORDS_URL}/{slug}").status_code, 404)


class ListRecordsTest(ApiTestCase):
    def test_lists_only_the_clients_records_newest_first(self):
        _, other_raw = ApiKey.objects.create_key(name="VCI")
        self.post_record(make_record("theirs"), raw_key=other_raw)
        older = json.loads(self.post_record(make_record("var-1")).content)["slug"]
        newer = json.loads(self.post_record(make_record("var-2")).content)["slug"]
        response = self.get(RECORDS_URL)
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["count"], 2)
        self.assertEqual([item["slug"] for item in body["items"]], [newer, older])
        self.assertNotIn("record", body["items"][0])

    def test_is_paginated(self):
        for i in range(3):
            self.post_record(make_record(str(i)))
        body = json.loads(self.get(f"{RECORDS_URL}?limit=2").content)
        self.assertEqual(len(body["items"]), 2)
        self.assertEqual(body["count"], 3)


class AuthTest(ApiTestCase):
    def test_a_missing_unknown_or_inactive_key_gets_401(self):
        inactive, inactive_raw = ApiKey.objects.create_key(name="Old")
        inactive.is_active = False
        inactive.save()
        cases = {
            "missing": self.client.get(SUBMISSIONS_URL),
            "unknown": self.get(SUBMISSIONS_URL, raw_key="css_unknown"),
            "inactive": self.get(SUBMISSIONS_URL, raw_key=inactive_raw),
            "post": self.post_record(make_record(), raw_key="css_unknown"),
        }
        for name, response in cases.items():
            with self.subTest(name):
                self.assertEqual(response.status_code, 401)
        self.assertFalse(Record.objects.exists())


class ReadSubmissionTest(ApiTestCase):
    def test_returns_the_clients_batch(self):
        batch = Batch.objects.create(
            api_key=self.api_key,
            affiliation_id=10007,
            affiliation_name="Hearing Loss VCEP",
            status=Batch.Status.PROCESSED_BY_CLINVAR,
            clinvar_submission_id="SUB000009",
            latest_response={"actions": []},
            summary_report={"totalCount": 1},
        )
        response = self.get(f"{SUBMISSIONS_URL}/{batch.slug}")
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["affiliation"], AFFILIATION)
        self.assertEqual(body["status"], "processed_by_clinvar")
        self.assertEqual(body["clinvar_submission_id"], "SUB000009")
        self.assertEqual(body["latest_response"], {"actions": []})
        self.assertEqual(body["summary_report"], {"totalCount": 1})

    def test_another_clients_batch_is_not_found(self):
        other, _ = ApiKey.objects.create_key(name="VCI")
        batch = Batch.objects.create(api_key=other)
        response = self.get(f"{SUBMISSIONS_URL}/{batch.slug}")
        self.assertEqual(response.status_code, 404)


class ListSubmissionsTest(ApiTestCase):
    def test_lists_only_the_clients_submissions_newest_first(self):
        other, _ = ApiKey.objects.create_key(name="VCI")
        Batch.objects.create(api_key=other)
        older = Batch.objects.create(api_key=self.api_key)
        newer = Batch.objects.create(api_key=self.api_key)
        response = self.get(SUBMISSIONS_URL)
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["count"], 2)
        slugs = [item["slug"] for item in body["items"]]
        self.assertEqual(slugs, [newer.slug, older.slug])

    def test_is_paginated(self):
        for _ in range(3):
            Batch.objects.create(api_key=self.api_key)
        response = self.get(f"{SUBMISSIONS_URL}?limit=2")
        self.assertEqual(len(json.loads(response.content)["items"]), 2)
        self.assertEqual(json.loads(response.content)["count"], 3)


class DocsTest(TestCase):
    def test_openapi_docs_render(self):
        response = self.client.get("/css/api/v1/docs")
        self.assertEqual(response.status_code, 200)

    def test_openapi_schema_describes_the_records_endpoints(self):
        schema = json.loads(self.client.get("/css/api/v1/openapi.json").content)
        self.assertEqual(set(schema["paths"]["/css/api/v1/records"]), {"get", "post"})
        self.assertIn("get", schema["paths"]["/css/api/v1/records/{slug}"])
        self.assertIn("germlineClassificationDescription", json.dumps(schema))
        self.assertNotIn("post", schema["paths"]["/css/api/v1/submissions"])

    def test_the_api_is_under_the_css_namespace(self):
        self.assertEqual(reverse("css:api-1:create_record"), "/css/api/v1/records")
