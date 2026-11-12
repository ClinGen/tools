import json
import logging
from datetime import UTC, datetime
from typing import Any
from unittest import mock

import requests
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings

from clinvar_submission_service.clients import (
    CLINVAR_TEST_URL,
    ClinVarClient,
    ClinVarError,
)
from clinvar_submission_service.tests.fakes import FakeClinVarClient, make_content

BASE_URL = "https://clinvar.example.org/apitest/v1"
API_KEY = "k" * 64
REPORT_URL = (
    "https://submit.ncbi.nlm.nih.gov/api/2.0/files/abc/sub999999-summary-report.json/"
)


def _response(
    status_code: int, body: object = None, headers: dict[str, str] | None = None
) -> requests.Response:
    """Returns a requests response with the given status, JSON body, and headers."""
    response = requests.Response()
    response.status_code = status_code
    # requests has no public way to set a response's body.
    response._content = b"" if body is None else json.dumps(body).encode()  # ruff: ignore[private-member-access]
    response.headers.update(headers or {})
    return response


def _status_body(
    status: str,
    *,
    error_code: int | None = None,
    report_url: str | None = None,
) -> dict[str, Any]:
    """Returns a ClinVar status response with one action."""
    files = [{"url": report_url}] if report_url else []
    return {
        "actions": [
            {
                "id": "SUB999999-1",
                "targetDb": "clinvar",
                "status": status,
                "updated": "2026-10-01T12:30:00.000000Z",
                "responses": [
                    {
                        "status": status,
                        "message": {"errorCode": error_code, "severity": "info"},
                        "files": files,
                        "objects": [],
                    }
                ],
            }
        ]
    }


class ClinVarClientTestCase(SimpleTestCase):
    def setUp(self):
        self.session = mock.create_autospec(requests.Session, instance=True)
        self.client_ = ClinVarClient(
            base_url=BASE_URL, api_key=API_KEY, session=self.session
        )


class SubmitTest(ClinVarClientTestCase):
    def test_posts_the_content_in_an_add_data_envelope(self):
        self.session.request.return_value = _response(201, {"id": "SUB999999"})
        content = make_content()
        self.assertEqual(self.client_.submit(content), "SUB999999")
        _, kwargs = self.session.request.call_args
        self.assertEqual(
            self.session.request.call_args.args[:2],
            ("POST", f"{BASE_URL}/submissions/"),
        )
        self.assertEqual(
            kwargs["json"],
            {
                "actions": [
                    {
                        "type": "AddData",
                        "targetDb": "clinvar",
                        "data": {"content": content},
                    }
                ]
            },
        )
        self.assertEqual(kwargs["headers"]["SP-API-KEY"], API_KEY)
        self.assertEqual(kwargs["headers"]["Content-Type"], "application/json")
        self.assertIn("timeout", kwargs)

    def test_a_dry_run_returns_no_id(self):
        self.session.request.return_value = _response(204)
        self.assertIsNone(self.client_.submit({}, dry_run=True))
        _, kwargs = self.session.request.call_args
        self.assertEqual(kwargs["params"], {"dry-run": "true"})

    def test_a_400_is_not_retryable_and_keeps_clinvars_message(self):
        self.session.request.return_value = _response(
            400, {"message": "Submission is incorrect"}
        )
        with self.assertRaises(ClinVarError) as caught:
            self.client_.submit({})
        self.assertFalse(caught.exception.retryable)
        self.assertIn("Submission is incorrect", str(caught.exception))

    def test_a_401_is_not_retryable(self):
        self.session.request.return_value = _response(
            401, {"message": "No valid API key provided"}
        )
        with self.assertRaises(ClinVarError) as caught:
            self.client_.submit({})
        self.assertFalse(caught.exception.retryable)

    def test_a_429_is_retryable_and_carries_retry_after(self):
        self.session.request.return_value = _response(
            429, headers={"Retry-After": "120"}
        )
        with self.assertRaises(ClinVarError) as caught:
            self.client_.submit({})
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(caught.exception.retry_after, 120)

    def test_a_5xx_is_retryable(self):
        self.session.request.return_value = _response(503)
        with self.assertRaises(ClinVarError) as caught:
            self.client_.submit({})
        self.assertTrue(caught.exception.retryable)
        self.assertIsNone(caught.exception.retry_after)

    def test_a_timeout_is_retryable(self):
        self.session.request.side_effect = requests.Timeout("timed out")
        with self.assertRaises(ClinVarError) as caught:
            self.client_.submit({})
        self.assertTrue(caught.exception.retryable)

    def test_a_connection_error_is_retryable(self):
        self.session.request.side_effect = requests.ConnectionError("refused")
        with self.assertRaises(ClinVarError) as caught:
            self.client_.submit({})
        self.assertTrue(caught.exception.retryable)

    def test_the_api_key_never_appears_in_logs_or_errors(self):
        self.session.request.side_effect = requests.ConnectionError(
            f"refused with SP-API-KEY {API_KEY}"
        )
        with (
            self.assertLogs("clinvar_submission_service", level=logging.DEBUG) as logs,
            self.assertRaises(ClinVarError) as caught,
        ):
            self.client_.submit({})
        self.assertNotIn(API_KEY, "\n".join(logs.output))
        self.assertNotIn(API_KEY, str(caught.exception))


class GetStatusTest(ClinVarClientTestCase):
    def test_reads_the_first_actions_status(self):
        for status in ("submitted", "processing", "processed", "error"):
            with self.subTest(status=status):
                self.session.request.return_value = _response(200, _status_body(status))
                self.assertEqual(self.client_.get_status("SUB999999").status, status)

    def test_gets_the_actions_endpoint_with_the_key(self):
        self.session.request.return_value = _response(200, _status_body("processing"))
        self.client_.get_status("SUB999999")
        args, kwargs = self.session.request.call_args
        self.assertEqual(
            args[:2], ("GET", f"{BASE_URL}/submissions/SUB999999/actions/")
        )
        self.assertEqual(kwargs["headers"]["SP-API-KEY"], API_KEY)

    def test_parses_the_update_time_error_code_and_report_url(self):
        body = _status_body("error", error_code=1, report_url=REPORT_URL)
        self.session.request.return_value = _response(200, body)
        status = self.client_.get_status("SUB999999")
        self.assertEqual(status.updated_at, datetime(2026, 10, 1, 12, 30, tzinfo=UTC))
        self.assertEqual(status.error_code, 1)
        self.assertEqual(status.summary_report_url, REPORT_URL)
        self.assertEqual(status.response, body)

    def test_a_response_without_files_has_no_report_url(self):
        self.session.request.return_value = _response(200, _status_body("processing"))
        status = self.client_.get_status("SUB999999")
        self.assertEqual(status.summary_report_url, "")
        self.assertIsNone(status.error_code)

    def test_a_malformed_response_is_retryable(self):
        self.session.request.return_value = _response(200, {"actions": []})
        with self.assertRaises(ClinVarError) as caught:
            self.client_.get_status("SUB999999")
        self.assertTrue(caught.exception.retryable)


class GetSummaryReportTest(ClinVarClientTestCase):
    def test_downloads_the_report_with_the_key(self):
        report = {"totalCount": 1, "totalSuccess": 1, "submissions": []}
        self.session.request.return_value = _response(200, report)
        self.assertEqual(self.client_.get_summary_report(REPORT_URL), report)
        args, kwargs = self.session.request.call_args
        self.assertEqual(args[:2], ("GET", REPORT_URL))
        self.assertEqual(kwargs["headers"]["SP-API-KEY"], API_KEY)


class FromSettingsTest(SimpleTestCase):
    @override_settings(CSS_CLINVAR_API_KEY="", CSS_CLINVAR_API_URL=BASE_URL)
    def test_a_missing_key_is_improperly_configured(self):
        with self.assertRaises(ImproperlyConfigured):
            ClinVarClient.from_settings()

    @override_settings(CSS_CLINVAR_API_KEY=API_KEY, CSS_CLINVAR_API_URL=BASE_URL + "/")
    def test_uses_the_settings(self):
        client = ClinVarClient.from_settings()
        self.assertEqual(client.base_url, BASE_URL)

    def test_tests_use_clinvars_test_endpoint(self):
        from django.conf import settings

        self.assertEqual(settings.CSS_CLINVAR_API_URL, CLINVAR_TEST_URL)
        self.assertEqual(settings.CSS_CLINVAR_API_KEY, "")


class FakeClinVarClientTest(SimpleTestCase):
    def test_submits_and_reports_status_like_clinvar(self):
        fake = FakeClinVarClient()
        clinvar_id = fake.submit(make_content())
        assert clinvar_id is not None
        self.assertEqual(fake.get_status(clinvar_id).status, "submitted")
        fake.set_status(clinvar_id, "processed", report={"totalCount": 0})
        status = fake.get_status(clinvar_id)
        self.assertEqual(
            fake.get_summary_report(status.summary_report_url), {"totalCount": 0}
        )
