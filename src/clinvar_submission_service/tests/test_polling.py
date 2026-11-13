import signal
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from clinvar_submission_service.clients import ClinVarError, ClinVarStatus
from clinvar_submission_service.content import Affiliation
from clinvar_submission_service.models import Batch, BatchRecord, Record
from clinvar_submission_service.polling import Poller, next_delay
from clinvar_submission_service.services import make_batch, save_record
from clinvar_submission_service.tests.fakes import FakeClinVarClient, make_record

MIN_DELAY = timedelta(minutes=5)
MAX_DELAY = timedelta(hours=6)

POLL_SETTINGS = {
    "CSS_POLL_MIN_DELAY": MIN_DELAY,
    "CSS_POLL_MAX_DELAY": MAX_DELAY,
    "CSS_POLLS_PER_PASS": 10,
}


@override_settings(**POLL_SETTINGS)
class PollerTestCase(TestCase):
    def setUp(self):
        self.fake = FakeClinVarClient()
        self.poller = Poller(self.fake)

    def _make(self, clinvar_id: str = "SUB000001", **fields: object) -> Batch:
        """Returns a submitted batch that's due to poll."""
        defaults = {
            "status": Batch.Status.SUBMITTED_TO_CLINVAR,
            "clinvar_submission_id": clinvar_id,
            "next_poll_at": timezone.now() - timedelta(minutes=1),
        }
        return Batch.objects.create(**(defaults | fields))


class NextDelayTest(PollerTestCase):
    def test_starts_at_the_minimum(self):
        self.assertEqual(next_delay(None, timezone.now()), MIN_DELAY)

    def test_doubles_the_time_since_the_last_poll(self):
        now = timezone.now()
        self.assertEqual(
            next_delay(now - timedelta(minutes=20), now), timedelta(minutes=40)
        )

    def test_is_capped_at_the_maximum(self):
        now = timezone.now()
        self.assertEqual(next_delay(now - timedelta(days=2), now), MAX_DELAY)

    def test_waits_at_least_as_long_as_retry_after(self):
        delay = next_delay(None, timezone.now(), retry_after=3600)
        self.assertEqual(delay, timedelta(hours=1))


class PollTest(PollerTestCase):
    def test_maps_each_clinvar_status_to_ours(self):
        expected = {
            "submitted": Batch.Status.SUBMITTED_TO_CLINVAR,
            "processing": Batch.Status.PROCESSING_AT_CLINVAR,
            "processed": Batch.Status.PROCESSED_BY_CLINVAR,
            "error": Batch.Status.ERROR_AT_CLINVAR,
        }
        for clinvar_status, ours in expected.items():
            with self.subTest(clinvar_status=clinvar_status):
                batch = self._make(clinvar_id=f"SUB-{clinvar_status}")
                self.fake.set_status(
                    batch.clinvar_submission_id, clinvar_status, report={}
                )
                self.poller.run_pass()
                batch.refresh_from_db()
                self.assertEqual(batch.status, ours)

    def test_a_processing_batch_is_polled_again_later(self):
        batch = self._make()
        self.fake.set_status("SUB000001", "processing")
        self.poller.run_pass()
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.PROCESSING_AT_CLINVAR)
        self.assertIsNotNone(batch.last_polled_at)
        self.assertIsNotNone(batch.clinvar_updated_at)
        self.assertEqual(batch.latest_response["actions"][0]["status"], "processing")
        assert batch.next_poll_at and batch.last_polled_at
        self.assertEqual(batch.next_poll_at - batch.last_polled_at, MIN_DELAY)

    def test_the_delay_grows_while_clinvar_is_still_processing(self):
        last_polled_at = timezone.now() - timedelta(minutes=30)
        batch = self._make(
            status=Batch.Status.PROCESSING_AT_CLINVAR,
            last_polled_at=last_polled_at,
        )
        self.fake.set_status("SUB000001", "processing")
        self.poller.run_pass()
        batch.refresh_from_db()
        assert batch.next_poll_at and batch.last_polled_at
        delay = batch.next_poll_at - batch.last_polled_at
        self.assertGreaterEqual(delay, timedelta(minutes=60))

    def test_a_processed_batch_stores_its_report_and_stops_polling(self):
        batch = self._make()
        report = {"totalCount": 1, "totalSuccess": 1}
        self.fake.set_status("SUB000001", "processed", report=report)
        self.poller.run_pass()
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.PROCESSED_BY_CLINVAR)
        self.assertEqual(batch.summary_report, report)
        self.assertIsNone(batch.next_poll_at)
        self.assertFalse(Batch.objects.due_to_poll().exists())

    def test_an_error_records_clinvars_error_code(self):
        batch = self._make()
        self.fake.set_status(
            "SUB000001", "error", error_code=2, report={"totalErrors": 1}
        )
        self.poller.run_pass()
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.ERROR_AT_CLINVAR)
        self.assertEqual(batch.clinvar_error_code, 2)

    def test_a_failed_report_download_is_retried_without_changing_the_status(self):
        batch = self._make()
        self.fake.set_status("SUB000001", "processed", report={"totalCount": 1})
        self.fake.report_error = ClinVarError("ClinVar returned 503", retryable=True)
        self.poller.run_pass()
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.SUBMITTED_TO_CLINVAR)
        self.assertIsNone(batch.summary_report)
        self.assertIsNotNone(batch.next_poll_at)

    def test_a_clinvar_error_backs_off_without_changing_the_status(self):
        batch = self._make()
        self.fake.status_error = ClinVarError("ClinVar returned 503", retryable=True)
        with mock.patch("clinvar_submission_service.polling.sentry_sdk") as sentry:
            self.poller.run_pass()
        sentry.capture_exception.assert_called_once()
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.SUBMITTED_TO_CLINVAR)
        assert batch.next_poll_at
        self.assertGreater(batch.next_poll_at, timezone.now())

    def test_a_429_waits_at_least_retry_after(self):
        batch = self._make()
        self.fake.status_error = ClinVarError(
            "ClinVar returned 429", retryable=True, retry_after=7200
        )
        self.poller.run_pass()
        batch.refresh_from_db()
        assert batch.next_poll_at
        self.assertGreaterEqual(
            batch.next_poll_at, timezone.now() + timedelta(seconds=7190)
        )

    def test_one_failing_batch_does_not_block_the_others(self):
        failing = self._make("SUB000001")
        working = self._make("SUB000002")
        self.fake.set_status("SUB000002", "processing")
        # SUB000001 has no status in the fake, so polling it raises KeyError.
        self.poller.run_pass()
        failing.refresh_from_db()
        working.refresh_from_db()
        self.assertEqual(failing.status, Batch.Status.SUBMITTED_TO_CLINVAR)
        self.assertEqual(working.status, Batch.Status.PROCESSING_AT_CLINVAR)
        assert failing.next_poll_at
        self.assertGreater(failing.next_poll_at, timezone.now())

    def test_send_failed_and_received_submissions_are_never_polled(self):
        for status in (
            Batch.Status.SEND_TO_CLINVAR_FAILED,
            Batch.Status.NOT_SENT_TO_CLINVAR,
        ):
            self._make(clinvar_id="", status=status)
        with mock.patch.object(self.fake, "get_status") as get_status:
            self.assertEqual(self.poller.run_pass(), 0)
        get_status.assert_not_called()

    @override_settings(CSS_POLLS_PER_PASS=1)
    def test_takes_one_batch_per_pass(self):
        self._make("SUB000001")
        self._make("SUB000002")
        self.fake.set_status("SUB000001", "processing")
        self.fake.set_status("SUB000002", "processing")
        self.assertEqual(self.poller.run_pass(), 1)

    def test_stopping_finishes_the_current_batch_first(self):
        first = self._make("SUB000001")
        second = self._make("SUB000002")
        self.fake.set_status("SUB000001", "processing")
        self.fake.set_status("SUB000002", "processing")
        real_get_status = self.fake.get_status

        def get_status_then_stop(clinvar_id: str) -> ClinVarStatus:
            self.poller.stop()
            return real_get_status(clinvar_id)

        with mock.patch.object(
            self.fake, "get_status", side_effect=get_status_then_stop
        ):
            self.assertEqual(self.poller.run_pass(), 1)
        first.refresh_from_db()
        second.refresh_from_db()
        polled = [s for s in (first, second) if s.last_polled_at]
        self.assertEqual(len(polled), 1)


@override_settings(**POLL_SETTINGS, CSS_POLL_SLEEP_SECONDS=0)
class CommandTest(TestCase):
    def setUp(self):
        self.fake = FakeClinVarClient()
        patcher = mock.patch(
            "clinvar_submission_service.polling.ClinVarClient.from_settings",
            return_value=self.fake,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_once_runs_one_pass(self):
        batch = Batch.objects.create(
            status=Batch.Status.SUBMITTED_TO_CLINVAR,
            clinvar_submission_id="SUB000001",
            next_poll_at=timezone.now(),
        )
        self.fake.set_status("SUB000001", "processing")
        call_command("poll_clinvar", "--once")
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.PROCESSING_AT_CLINVAR)

    def test_sigterm_stops_the_loop(self):
        handlers = {}

        def fake_signal(signum: int, handler: object) -> None:
            handlers[signum] = handler

        def sleep_then_sigterm(_seconds: float) -> None:
            handlers[signal.SIGTERM](signal.SIGTERM, None)

        with (
            mock.patch(
                "clinvar_submission_service.management.commands.poll_clinvar.signal.signal",
                side_effect=fake_signal,
            ),
            mock.patch(
                "clinvar_submission_service.management.commands.poll_clinvar.time.sleep",
                side_effect=sleep_then_sigterm,
            ) as sleep,
        ):
            call_command("poll_clinvar")
        sleep.assert_called_once()


ERRORS = [{"output": {"errors": [{"userMessage": "This record is a duplicate."}]}}]


class RecordResultsTest(PollerTestCase):
    def setUp(self):
        super().setUp()
        self.records = [_waiting("var-1"), _waiting("var-2")]
        self.batch = make_batch(self.records)
        Batch.objects.filter(pk=self.batch.pk).update(
            status=Batch.Status.SUBMITTED_TO_CLINVAR,
            clinvar_submission_id="SUB000001",
            next_poll_at=timezone.now() - timedelta(minutes=1),
        )

    def _report(self, *results: dict) -> dict:
        return {"totalCount": len(results), "submissions": list(results)}

    def _attempt(self, tool_id: str) -> BatchRecord:
        return BatchRecord.objects.select_related("record").get(
            batch=self.batch, record__tool_id=tool_id
        )

    def test_a_processed_batch_accepts_every_record_with_its_scv(self):
        report = self._report(
            _success("var-1", "SCV000000001"), _success("var-2", "SCV000000002")
        )
        self.fake.set_status("SUB000001", "processed", report=report)
        self.poller.run_pass()
        for tool_id, scv in [("var-1", "SCV000000001"), ("var-2", "SCV000000002")]:
            with self.subTest(tool_id):
                attempt = self._attempt(tool_id)
                self.assertEqual(attempt.result, BatchRecord.Result.SUCCESS)
                self.assertEqual(attempt.scv, scv)
                self.assertEqual(
                    attempt.record.status, Record.Status.SUCCEEDED_AT_CLINVAR
                )
                self.assertEqual(attempt.record.clinvar_accession, scv)

    def test_a_partly_failed_batch_returns_the_failures_to_waiting(self):
        report = self._report(
            _success("var-1", "SCV000000001"),
            {
                "identifiers": {"localID": "var-2"},
                "processingStatus": "Error",
                "errors": ERRORS,
            },
        )
        self.fake.set_status("SUB000001", "error", error_code=1, report=report)
        self.poller.run_pass()
        accepted, failed = self._attempt("var-1"), self._attempt("var-2")
        self.assertEqual(accepted.record.status, Record.Status.SUCCEEDED_AT_CLINVAR)
        self.assertEqual(failed.result, BatchRecord.Result.ERROR)
        self.assertEqual(failed.errors, ERRORS)
        self.assertEqual(failed.scv, "")
        self.assertEqual(failed.record.status, Record.Status.WAITING_FOR_BATCH)
        # The failed record can join a later batch.
        self.assertEqual(make_batch([failed.record]).records.get(), failed.record)

    def test_an_unmatched_tool_id_is_logged_and_skipped(self):
        report = self._report(
            _success("var-1", "SCV000000001"), _success("nobody", "SCV000000009")
        )
        self.fake.set_status("SUB000001", "processed", report=report)
        with self.assertLogs("clinvar_submission_service.services", "WARNING") as logs:
            self.poller.run_pass()
        self.assertIn("nobody", logs.output[0])
        self.assertEqual(self._attempt("var-1").result, BatchRecord.Result.SUCCESS)
        unreported = self._attempt("var-2")
        self.assertEqual(unreported.result, "")
        self.assertEqual(unreported.record.status, Record.Status.IN_BATCH)


def _success(tool_id: str, scv: str) -> dict:
    return {
        "identifiers": {"localID": tool_id, "clinvarAccession": scv},
        "processingStatus": "Success",
    }


def _waiting(tool_id: str) -> Record:
    record, _ = save_record(
        api_key=None,
        affiliation=Affiliation(id=10007, name="Hearing Loss VCEP"),
        payload=make_record(tool_id),
    )
    return record
