import json
from unittest import mock

from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from clinvar_submission_service.api.auth import API_KEY_HEADER
from clinvar_submission_service.models import ApiKey, Batch, BatchRecord, Record
from clinvar_submission_service.tests.fakes import (
    FakeClinVarClient,
    make_content,
    make_record,
)
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

    def get(self, url: str, raw_key: str | None = None):
        return self.client.get(url, headers={API_KEY_HEADER: raw_key or self.raw_key})


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
        self.assertEqual(record.tool_id, "var-2")
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

    def test_the_same_tool_id_from_another_affiliation_is_a_new_record(self):
        self.post_record(make_record("var-1"))
        other = {"id": 10008, "name": "Cardiomyopathy VCEP"}
        response = self.post_body(
            {"affiliation": other, "record": make_record("var-1")}
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Record.objects.count(), 2)

    def test_records_without_a_tool_id_are_never_replaced(self):
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
        self.assertEqual(body["tool_id"], "var-1")
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
            "missing": self.client.get(RECORDS_URL),
            "unknown": self.get(RECORDS_URL, raw_key="css_unknown"),
            "inactive": self.get(RECORDS_URL, raw_key=inactive_raw),
            "post": self.post_record(make_record(), raw_key="css_unknown"),
        }
        for name, response in cases.items():
            with self.subTest(name):
                self.assertEqual(response.status_code, 401)
        self.assertFalse(Record.objects.exists())


class DocsTest(TestCase):
    def test_openapi_docs_render(self):
        response = self.client.get("/css/api/v1/docs")
        self.assertEqual(response.status_code, 200)

    def test_openapi_schema_describes_the_records_endpoints(self):
        schema = json.loads(self.client.get("/css/api/v1/openapi.json").content)
        self.assertEqual(set(schema["paths"]["/css/api/v1/records"]), {"get", "post"})
        self.assertIn("get", schema["paths"]["/css/api/v1/records/{slug}"])
        self.assertIn("germlineClassificationDescription", json.dumps(schema))
        self.assertFalse(any("submissions" in path for path in schema["paths"]))

    def test_the_old_batch_endpoints_are_gone(self):
        _, raw_key = ApiKey.objects.create_key(name="GCI")
        batch = Batch.objects.create()
        for url in [SUBMISSIONS_URL, f"{SUBMISSIONS_URL}/{batch.slug}"]:
            with self.subTest(url):
                response = self.client.get(url, headers={API_KEY_HEADER: raw_key})
                self.assertEqual(response.status_code, 404)

    def test_the_api_is_under_the_css_namespace(self):
        self.assertEqual(reverse("css:api-1:create_record"), "/css/api/v1/records")


class WithdrawRecordTest(ApiTestCase):
    def withdraw(self, slug: str, raw_key: str | None = None):
        return self.client.post(
            f"{RECORDS_URL}/{slug}/withdraw",
            headers={API_KEY_HEADER: raw_key or self.raw_key},
        )

    def test_the_client_can_withdraw_a_waiting_record(self):
        slug = json.loads(self.post_record(make_record()).content)["slug"]
        response = self.withdraw(slug)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["status"], "withdrawn")
        record = Record.objects.get()
        self.assertEqual(record.status, Record.Status.WITHDRAWN)
        latest = record.history.first()  # type: ignore
        self.assertEqual(latest.history_change_reason, "Withdrawn by the GCI")

    def test_a_batched_or_accepted_record_cant_be_withdrawn(self):
        slug = json.loads(self.post_record(make_record()).content)["slug"]
        for status in [
            Record.Status.IN_BATCH,
            Record.Status.SUCCEEDED_AT_CLINVAR,
            Record.Status.WITHDRAWN,
        ]:
            with self.subTest(status):
                Record.objects.update(status=status)
                response = self.withdraw(slug)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(
                    json.loads(response.content)["detail"],
                    "Only a record that's waiting for a batch can be withdrawn.",
                )
                self.assertEqual(Record.objects.get().status, status)

    def test_another_clients_record_is_not_found(self):
        _, other_raw = ApiKey.objects.create_key(name="VCI")
        slug = json.loads(self.post_record(make_record(), raw_key=other_raw).content)[
            "slug"
        ]
        self.assertEqual(self.withdraw(slug).status_code, 404)
        self.assertEqual(Record.objects.get().status, Record.Status.WAITING_FOR_BATCH)


class RecordAttemptsTest(ApiTestCase):
    """Tests that a record's detail shows each batch it was sent in."""

    def setUp(self):
        super().setUp()
        self.post_record(make_record("var-1"))
        self.record = Record.objects.get()
        self.url = f"{RECORDS_URL}/{self.record.slug}"

    def _batch(self, **fields: object) -> Batch:
        defaults = {"affiliation_id": 10007, "affiliation_name": "Hearing Loss VCEP"}
        return Batch.objects.create(**(defaults | fields))

    def _attempt(self, batch: Batch, **fields: object) -> BatchRecord:
        return BatchRecord.objects.create(
            batch=batch, record=self.record, position=0, **fields
        )

    def test_a_waiting_record_has_no_attempts_or_batch(self):
        body = self.get(self.url).json()
        self.assertEqual(body["attempts"], [])
        self.assertIsNone(body["current_batch"])
        self.assertEqual(body["status_label"], "Waiting")
        self.assertEqual(
            body["status_description"],
            Record.STATUS_HELP[Record.Status.WAITING_FOR_BATCH],
        )

    def test_a_batched_record_shows_its_batch(self):
        batch = self._batch(
            status=Batch.Status.SUBMITTED_TO_CLINVAR, clinvar_submission_id="SUB1"
        )
        self._attempt(batch)
        Record.objects.filter(pk=self.record.pk).update(status=Record.Status.IN_BATCH)
        body = self.get(self.url).json()
        self.assertEqual(body["current_batch"], batch.slug)
        [attempt] = body["attempts"]
        self.assertEqual(attempt["batch"]["slug"], batch.slug)
        self.assertEqual(attempt["batch"]["status"], "submitted_to_clinvar")
        self.assertEqual(attempt["batch"]["status_label"], "Submitted")
        self.assertEqual(
            attempt["batch"]["status_description"],
            Batch.STATUS_HELP[Batch.Status.SUBMITTED_TO_CLINVAR],
        )
        self.assertEqual(attempt["batch"]["clinvar_submission_id"], "SUB1")
        self.assertEqual(attempt["result"], "")
        self.assertIsNone(attempt["errors"])

    def test_shows_a_failed_attempt_then_a_successful_one_in_order(self):
        errors = [{"output": {"errors": [{"userMessage": "Bad HGVS."}]}}]
        failed = self._batch(status=Batch.Status.ERROR_AT_CLINVAR, clinvar_error_code=2)
        self._attempt(failed, result=BatchRecord.Result.ERROR, errors=errors)
        succeeded = self._batch(status=Batch.Status.PROCESSED_BY_CLINVAR)
        self._attempt(succeeded, result=BatchRecord.Result.SUCCESS, scv="SCV000000001")
        body = self.get(self.url).json()
        first, second = body["attempts"]
        self.assertEqual(first["batch"]["slug"], failed.slug)
        self.assertEqual(first["result"], "Error")
        self.assertEqual(first["errors"], errors)
        self.assertEqual(first["batch"]["clinvar_error_code"], 2)
        self.assertEqual(first["batch"]["status_description"], Batch.ERROR_CODE_HELP[2])
        self.assertEqual(second["batch"]["slug"], succeeded.slug)
        self.assertEqual(second["result"], "Success")
        self.assertEqual(second["scv"], "SCV000000001")

    def test_never_shows_who_made_a_batch_or_any_api_key(self):
        self._attempt(self._batch())
        text = self.get(self.url).content.decode()
        for name in ("made_by", "api_key", "staff"):
            self.assertNotIn(name, text)

    def test_reading_a_record_takes_the_same_queries_for_any_number_of_attempts(self):
        self._attempt(self._batch())
        with CaptureQueriesContext(connection) as one:
            self.get(self.url)
        for _ in range(3):
            self._attempt(self._batch())
        with self.assertNumQueries(len(one)):
            self.get(self.url)


BATCHES_URL = "/css/api/v1/batches"


class BatchesTest(ApiTestCase):
    """Tests that a client reads only its own records in the batches that hold them."""

    def setUp(self):
        super().setUp()
        self.other_key, self.other_raw_key = ApiKey.objects.create_key(name="VCI")
        self.mine = self._record("var-1", self.raw_key)
        self.theirs = self._record("var-2", self.other_raw_key)

    def _record(self, tool_id: str, raw_key: str) -> Record:
        slug = self.post_record(make_record(tool_id), raw_key=raw_key).json()["slug"]
        return Record.objects.get(slug=slug)

    def _batch(self, *records: Record, **fields: object) -> Batch:
        defaults = {"affiliation_id": 10007, "affiliation_name": "Hearing Loss VCEP"}
        batch = Batch.objects.create(**(defaults | fields))
        for position, record in enumerate(records):
            BatchRecord.objects.create(batch=batch, record=record, position=position)
        return batch

    def test_lists_only_batches_holding_the_clients_records_newest_first(self):
        older = self._batch(self.mine)
        self._batch(self.theirs)
        newer = self._batch(self.mine)
        body = self.get(BATCHES_URL).json()
        self.assertEqual([b["slug"] for b in body["items"]], [newer.slug, older.slug])
        self.assertEqual(body["count"], 2)

    def test_reads_a_batch_with_its_status_and_the_clients_records(self):
        batch = self._batch(
            self.mine,
            status=Batch.Status.ERROR_AT_CLINVAR,
            clinvar_submission_id="SUB1",
            clinvar_error_code=1,
        )
        BatchRecord.objects.filter(record=self.mine).update(
            result=BatchRecord.Result.ERROR, errors=[{"userMessage": "Bad HGVS."}]
        )
        body = self.get(f"{BATCHES_URL}/{batch.slug}").json()
        self.assertEqual(body["slug"], batch.slug)
        self.assertEqual(body["affiliation"], AFFILIATION)
        self.assertEqual(body["status"], "error_at_clinvar")
        self.assertEqual(body["status_label"], "Error")
        self.assertEqual(body["status_description"], Batch.ERROR_CODE_HELP[1])
        self.assertEqual(body["clinvar_submission_id"], "SUB1")
        self.assertEqual(body["clinvar_error_code"], 1)
        self.assertEqual(body["record_count"], 1)
        [record] = body["records"]
        self.assertEqual(record["slug"], self.mine.slug)
        self.assertEqual(record["tool_id"], "var-1")
        self.assertEqual(record["result"], "Error")
        self.assertEqual(record["errors"], [{"userMessage": "Bad HGVS."}])

    def test_shows_each_client_only_its_own_records_in_a_shared_batch(self):
        batch = self._batch(self.theirs, self.mine)
        mine = self.get(f"{BATCHES_URL}/{batch.slug}").json()
        theirs = self.get(f"{BATCHES_URL}/{batch.slug}", self.other_raw_key).json()
        self.assertEqual([r["slug"] for r in mine["records"]], [self.mine.slug])
        self.assertEqual([r["slug"] for r in theirs["records"]], [self.theirs.slug])
        self.assertEqual(mine["record_count"], 1)
        listed = self.get(BATCHES_URL).json()["items"]
        self.assertEqual(listed[0]["record_count"], 1)

    def test_a_batch_with_several_of_the_clients_records_is_listed_once(self):
        second = self._record("var-3", self.raw_key)
        batch = self._batch(self.mine, self.theirs, second)
        [listed] = self.get(BATCHES_URL).json()["items"]
        self.assertEqual(listed["record_count"], 2)
        body = self.get(f"{BATCHES_URL}/{batch.slug}").json()
        self.assertEqual(
            [r["slug"] for r in body["records"]], [self.mine.slug, second.slug]
        )

    def test_another_clients_batch_is_not_found(self):
        batch = self._batch(self.theirs)
        self.assertEqual(self.get(f"{BATCHES_URL}/{batch.slug}").status_code, 404)
        self.assertEqual(self.get(BATCHES_URL).json()["items"], [])

    def test_filters_by_status_and_affiliation(self):
        sent = self._batch(self.mine, status=Batch.Status.SUBMITTED_TO_CLINVAR)
        self._batch(self.mine, affiliation_id=10008)
        by_status = self.get(f"{BATCHES_URL}?status=submitted_to_clinvar").json()
        self.assertEqual([b["slug"] for b in by_status["items"]], [sent.slug])
        by_affiliation = self.get(f"{BATCHES_URL}?affiliation=10008").json()
        self.assertEqual(len(by_affiliation["items"]), 1)
        self.assertEqual(by_affiliation["items"][0]["affiliation"]["id"], 10008)
        self.assertEqual(self.get(f"{BATCHES_URL}?status=nope").status_code, 422)

    def test_never_shows_who_made_a_batch_or_any_api_key(self):
        batch = self._batch(self.mine)
        for url in (BATCHES_URL, f"{BATCHES_URL}/{batch.slug}"):
            text = self.get(url).content.decode()
            for name in ("made_by", "api_key", "staff"):
                self.assertNotIn(name, text)

    def test_the_openapi_schema_has_the_batches_paths(self):
        paths = self.client.get("/css/api/v1/openapi.json").json()["paths"]
        self.assertIn("/css/api/v1/batches", paths)
        self.assertIn("/css/api/v1/batches/{slug}", paths)
