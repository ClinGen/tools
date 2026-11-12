"""Tests send_dummy_records.py, which POSTs random dummy records to a running CSS."""

import random
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import TestCase, mock

from send_dummy_records import AFFILIATIONS, dummy_body, main, resent

from clinvar_submission_service.content import GermlineRecord, RecordRequest


def _response(status: int, body: dict | None = None) -> mock.Mock:
    response = mock.Mock(status_code=status)
    response.json.return_value = body or {}
    return response


class DummyBodyTest(TestCase):
    def test_every_record_is_valid_for_the_css(self):
        rng = random.Random(1)
        for _ in range(200):
            body = dummy_body(rng)
            RecordRequest.model_validate(body)
            GermlineRecord.model_validate(body["record"])
            self.assertIn(body["affiliation"], AFFILIATIONS)

    def test_some_records_are_updates_with_an_scv(self):
        rng = random.Random(2)
        records = [dummy_body(rng)["record"] for _ in range(200)]
        updates = [r for r in records if r["recordStatus"] == "update"]
        self.assertTrue(10 < len(updates) < 90)
        self.assertTrue(all(r["clinvarAccession"].startswith("SCV") for r in updates))

    def test_records_differ_between_runs(self):
        first = [dummy_body(random.Random())["record"]["localID"] for _ in range(5)]
        second = [dummy_body(random.Random())["record"]["localID"] for _ in range(5)]
        self.assertNotEqual(first, second)

    def test_a_resent_record_keeps_its_tool_id_and_changes_its_classification(self):
        rng = random.Random(3)
        body = dummy_body(rng)
        again = resent(body, rng)
        self.assertEqual(again["record"]["localID"], body["record"]["localID"])
        self.assertEqual(again["affiliation"], body["affiliation"])
        old = body["record"]["germlineClassification"]
        new = again["record"]["germlineClassification"]
        self.assertNotEqual(
            new["germlineClassificationDescription"],
            old["germlineClassificationDescription"],
        )
        RecordRequest.model_validate(again)


class MainTest(TestCase):
    def run_main(self, args: list[str], key: str | None = "css_dummy"):
        out, err = StringIO(), StringIO()
        env = {} if key is None else {"CSS_DUMMY_API_KEY": key}
        with (
            mock.patch.dict("os.environ", env, clear=True),
            mock.patch("send_dummy_records.load_dotenv"),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = main(args)
        return code, out.getvalue(), err.getvalue()

    def test_posts_each_record_with_the_key(self):
        with mock.patch("send_dummy_records.requests.post") as post:
            post.return_value = _response(
                201, {"slug": "R1", "status": "waiting_for_batch"}
            )
            code, out, _ = self.run_main(["--count", "3", "--url", "http://css.test"])
        self.assertEqual(code, 0)
        self.assertEqual(post.call_count, 3)
        url = post.call_args.args[0]
        self.assertEqual(url, "http://css.test/css/api/v1/records")
        self.assertEqual(post.call_args.kwargs["headers"], {"X-API-Key": "css_dummy"})
        self.assertIn("R1", out)
        self.assertIn("new", out)

    def test_resend_sends_records_again_with_the_same_tool_id(self):
        with mock.patch("send_dummy_records.requests.post") as post:
            post.side_effect = [
                _response(201, {"slug": "R1", "status": "waiting_for_batch"}),
                _response(201, {"slug": "R2", "status": "waiting_for_batch"}),
                _response(200, {"slug": "R1", "status": "waiting_for_batch"}),
            ]
            code, out, _ = self.run_main(["--count", "2", "--resend"])
        self.assertEqual(code, 0)
        sent = [
            call.kwargs["json"]["record"]["localID"] for call in post.call_args_list
        ]
        self.assertEqual(len(sent), 3)
        self.assertIn(sent[2], sent[:2])
        self.assertIn("replaced", out)

    def test_a_missing_key_exits_with_a_plain_message(self):
        with mock.patch("send_dummy_records.requests.post") as post:
            code, _, err = self.run_main([], key=None)
        self.assertEqual(code, 1)
        self.assertIn("Set CSS_DUMMY_API_KEY", err)
        post.assert_not_called()

    def test_a_rejected_key_exits_with_a_plain_message(self):
        with mock.patch("send_dummy_records.requests.post") as post:
            post.return_value = _response(401)
            code, _, err = self.run_main([])
        self.assertEqual(code, 1)
        self.assertIn("The CSS didn't accept the API key", err)
        post.assert_called_once()

    def test_an_unreachable_css_exits_with_a_plain_message(self):
        with mock.patch("send_dummy_records.requests.post") as post:
            post.side_effect = __import__("requests").ConnectionError("refused")
            code, _, err = self.run_main([])
        self.assertEqual(code, 1)
        self.assertIn("Couldn't reach the CSS", err)
