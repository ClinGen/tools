import json
from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.urls import reverse

from clinvar_submission_service.api_auth import API_KEY_HEADER
from clinvar_submission_service.clients import ClinVarError
from clinvar_submission_service.content import MAX_RECORDS
from clinvar_submission_service.fakes import (
    FakeClinVarClient,
    make_content,
    make_record,
)
from clinvar_submission_service.models import ApiKey, Record, Submission
from clinvar_submission_service.services import forward_submission

CONTENT = make_content()

SUBMISSIONS_URL = "/css/api/v1/submissions"


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

    def post(self, body: object, raw_key: str | None = None):
        return self.client.post(
            SUBMISSIONS_URL,
            body,
            content_type="application/json",
            headers={API_KEY_HEADER: raw_key or self.raw_key},
        )

    def get(self, url: str, raw_key: str | None = None):
        return self.client.get(url, headers={API_KEY_HEADER: raw_key or self.raw_key})


class ForwardSubmissionTest(ApiTestCase):
    def test_a_submission_clinvar_accepts_is_submitted(self):
        submission = Submission.objects.create(payload=CONTENT)
        forward_submission(submission)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.SUBMITTED)
        self.assertEqual(submission.clinvar_submission_id, "SUB000001")
        self.assertIsNotNone(submission.next_poll_at)
        self.assertEqual(self.fake.submitted, [CONTENT])

    def test_a_submission_clinvar_rejects_is_send_failed(self):
        self.fake.submit_error = ClinVarError("ClinVar returned 400", retryable=False)
        submission = Submission.objects.create(payload=CONTENT)
        forward_submission(submission)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.SEND_FAILED)
        self.assertEqual(submission.error_message, "ClinVar returned 400")
        self.assertEqual(submission.clinvar_submission_id, "")

    def test_a_failed_send_is_not_retried(self):
        self.fake.submit_error = ClinVarError("ClinVar returned 503", retryable=True)
        with mock.patch.object(self.fake, "submit", wraps=self.fake.submit) as submit:
            forward_submission(Submission.objects.create(payload=CONTENT))
        submit.assert_called_once()

    def test_an_unconfigured_client_is_send_failed(self):
        submission = Submission.objects.create(payload=CONTENT)
        with mock.patch(
            "clinvar_submission_service.services.ClinVarClient.from_settings",
            side_effect=ImproperlyConfigured("Set CSS_CLINVAR_API_KEY."),
        ):
            forward_submission(submission)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.SEND_FAILED)


class CreateSubmissionTest(ApiTestCase):
    def test_saves_and_forwards_the_submission(self):
        response = self.post(CONTENT)
        self.assertEqual(response.status_code, 201)
        submission = Submission.objects.get()
        self.assertEqual(submission.api_key, self.api_key)
        self.assertEqual(submission.payload, CONTENT)
        self.assertEqual(json.loads(response.content)["slug"], submission.slug)
        self.assertEqual(json.loads(response.content)["status"], "submitted")
        self.assertEqual(
            json.loads(response.content)["clinvar_submission_id"], "SUB000001"
        )

    def test_says_so_when_clinvar_rejects_it(self):
        self.fake.submit_error = ClinVarError("ClinVar returned 400", retryable=False)
        response = self.post(CONTENT)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(json.loads(response.content)["status"], "send_failed")
        self.assertEqual(
            json.loads(response.content)["error_message"], "ClinVar returned 400"
        )

    def test_rejects_a_body_that_is_not_an_object(self):
        response = self.post(["not", "an", "object"])
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Submission.objects.exists())

    # A full submission is bigger than Django's default upload limit.
    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=None)
    def test_rejects_too_many_records(self):
        records = [make_record(str(i)) for i in range(MAX_RECORDS + 1)]
        response = self.post(make_content(*records))
        self.assertEqual(response.status_code, 422)
        self.assertFalse(Submission.objects.exists())

    def test_saves_the_contents_fields_and_records(self):
        content = make_content(
            make_record("var-1"),
            make_record(
                "var-2",
                recordStatus="update",
                clinvarAccession="SCV000000002",
            ),
        )
        content["behalfOrgID"] = 506185
        self.post(content)
        submission = Submission.objects.get()
        self.assertEqual(submission.assertion_criteria_db, "PubMed")
        self.assertEqual(submission.assertion_criteria_id, "25741868")
        self.assertEqual(submission.behalf_org_id, 506185)
        first, second = submission.records.all()  # type: ignore
        self.assertEqual(first.local_id, "var-1")
        self.assertEqual(first.hgvs, "NC_000017.11:g.43045712T>C")
        self.assertEqual(first.gene_symbol, "BRCA1")
        self.assertEqual(first.condition_id, "MONDO:0011450")
        self.assertEqual(first.classification, "Likely pathogenic")
        self.assertEqual(first.mode_of_inheritance, "Autosomal dominant inheritance")
        self.assertEqual(first.date_last_evaluated.isoformat(), "2026-10-01")
        self.assertEqual(first.collection_method, "curation")
        self.assertEqual(second.record_status, "update")
        self.assertEqual(second.clinvar_accession, "SCV000000002")
        self.assertEqual(first.history.count(), 1)

    def test_forwards_the_payload_as_sent(self):
        self.post(CONTENT)
        self.assertEqual(self.fake.submitted, [CONTENT])
        self.assertEqual(Submission.objects.get().payload, CONTENT)

    def test_rejects_content_that_does_not_match_and_saves_nothing(self):
        cases = {
            "unknown field": make_content(make_record(unknownField="x")),
            "bad classification": make_content(
                make_record(
                    germlineClassification={
                        "germlineClassificationDescription": "Probably fine"
                    }
                )
            ),
            "update without an accession": make_content(
                make_record(recordStatus="update")
            ),
            "two conditions": make_content(
                make_record(
                    conditionSet={
                        "condition": [
                            {"db": "MONDO", "id": "MONDO:0011450"},
                            {"db": "MONDO", "id": "MONDO:0007254"},
                        ]
                    }
                )
            ),
            "no records": {"germlineSubmission": []},
            "older clinvarSubmission records": {"clinvarSubmission": [make_record()]},
        }
        for name, content in cases.items():
            with self.subTest(name):
                self.assertEqual(self.post(content).status_code, 422)
        self.assertFalse(Submission.objects.exists())
        self.assertFalse(Record.objects.exists())


class AuthTest(ApiTestCase):
    def test_a_missing_unknown_or_inactive_key_gets_401(self):
        inactive, inactive_raw = ApiKey.objects.create_key(name="Old")
        inactive.is_active = False
        inactive.save()
        cases = {
            "missing": self.client.get(SUBMISSIONS_URL),
            "unknown": self.get(SUBMISSIONS_URL, raw_key="css_unknown"),
            "inactive": self.get(SUBMISSIONS_URL, raw_key=inactive_raw),
            "post": self.post(CONTENT, raw_key="css_unknown"),
        }
        for name, response in cases.items():
            with self.subTest(name):
                self.assertEqual(response.status_code, 401)
        self.assertFalse(Submission.objects.exists())


class ReadSubmissionTest(ApiTestCase):
    def test_returns_the_clients_submission(self):
        submission = Submission.objects.create(
            api_key=self.api_key,
            payload=CONTENT,
            status=Submission.Status.PROCESSED,
            clinvar_submission_id="SUB000009",
            latest_response={"actions": []},
            summary_report={"totalCount": 1},
        )
        response = self.get(f"{SUBMISSIONS_URL}/{submission.slug}")
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["status"], "processed")
        self.assertEqual(body["clinvar_submission_id"], "SUB000009")
        self.assertEqual(body["latest_response"], {"actions": []})
        self.assertEqual(body["summary_report"], {"totalCount": 1})

    def test_another_clients_submission_is_not_found(self):
        other, _ = ApiKey.objects.create_key(name="VCI")
        submission = Submission.objects.create(api_key=other, payload=CONTENT)
        response = self.get(f"{SUBMISSIONS_URL}/{submission.slug}")
        self.assertEqual(response.status_code, 404)


class ListSubmissionsTest(ApiTestCase):
    def test_lists_only_the_clients_submissions_newest_first(self):
        other, _ = ApiKey.objects.create_key(name="VCI")
        Submission.objects.create(api_key=other, payload=CONTENT)
        older = Submission.objects.create(api_key=self.api_key, payload=CONTENT)
        newer = Submission.objects.create(api_key=self.api_key, payload=CONTENT)
        response = self.get(SUBMISSIONS_URL)
        self.assertEqual(response.status_code, 200)
        body = json.loads(response.content)
        self.assertEqual(body["count"], 2)
        slugs = [item["slug"] for item in body["items"]]
        self.assertEqual(slugs, [newer.slug, older.slug])

    def test_is_paginated(self):
        for _ in range(3):
            Submission.objects.create(api_key=self.api_key, payload=CONTENT)
        response = self.get(f"{SUBMISSIONS_URL}?limit=2")
        self.assertEqual(len(json.loads(response.content)["items"]), 2)
        self.assertEqual(json.loads(response.content)["count"], 3)


class DocsTest(TestCase):
    def test_openapi_docs_render(self):
        response = self.client.get("/css/api/v1/docs")
        self.assertEqual(response.status_code, 200)

    def test_openapi_schema_lists_clinvars_fields(self):
        response = self.client.get("/css/api/v1/openapi.json")
        self.assertContains(response, "germlineSubmission")
        self.assertContains(response, "germlineClassificationDescription")

    def test_the_api_is_under_the_css_namespace(self):
        self.assertEqual(
            reverse("css:api-1:create_submission"), "/css/api/v1/submissions"
        )
