import signal
from datetime import timedelta
from unittest import mock

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from clinvar_submission_service.clients import ClinVarError, ClinVarStatus
from clinvar_submission_service.fakes import FakeClinVarClient
from clinvar_submission_service.models import Submission
from clinvar_submission_service.polling import Poller, next_delay

MIN_DELAY = timedelta(minutes=5)
MAX_DELAY = timedelta(hours=6)

POLL_SETTINGS = {
    "CSS_POLL_MIN_DELAY": MIN_DELAY,
    "CSS_POLL_MAX_DELAY": MAX_DELAY,
    "CSS_POLL_BATCH_SIZE": 10,
}


@override_settings(**POLL_SETTINGS)
class PollerTestCase(TestCase):
    def setUp(self):
        self.fake = FakeClinVarClient()
        self.poller = Poller(self.fake)

    def _make(self, clinvar_id: str = "SUB000001", **fields: object) -> Submission:
        """Returns a submitted submission that's due to poll."""
        defaults = {
            "status": Submission.Status.SUBMITTED,
            "clinvar_submission_id": clinvar_id,
            "next_poll_at": timezone.now() - timedelta(minutes=1),
        }
        return Submission.objects.create(payload={}, **(defaults | fields))


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
    def test_a_processing_submission_is_polled_again_later(self):
        submission = self._make()
        self.fake.set_status("SUB000001", "processing")
        self.poller.run_pass()
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.PROCESSING)
        self.assertIsNotNone(submission.last_polled_at)
        self.assertIsNotNone(submission.clinvar_updated_at)
        self.assertEqual(
            submission.latest_response["actions"][0]["status"], "processing"
        )
        assert submission.next_poll_at and submission.last_polled_at
        self.assertEqual(submission.next_poll_at - submission.last_polled_at, MIN_DELAY)

    def test_the_delay_grows_while_clinvar_is_still_processing(self):
        last_polled_at = timezone.now() - timedelta(minutes=30)
        submission = self._make(
            status=Submission.Status.PROCESSING, last_polled_at=last_polled_at
        )
        self.fake.set_status("SUB000001", "processing")
        self.poller.run_pass()
        submission.refresh_from_db()
        assert submission.next_poll_at and submission.last_polled_at
        delay = submission.next_poll_at - submission.last_polled_at
        self.assertGreaterEqual(delay, timedelta(minutes=60))

    def test_a_processed_submission_stores_its_report_and_stops_polling(self):
        submission = self._make()
        report = {"totalCount": 1, "totalSuccess": 1}
        self.fake.set_status("SUB000001", "processed", report=report)
        self.poller.run_pass()
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.PROCESSED)
        self.assertEqual(submission.summary_report, report)
        self.assertIsNone(submission.next_poll_at)
        self.assertFalse(Submission.objects.due_to_poll().exists())

    def test_an_error_records_clinvars_error_code(self):
        submission = self._make()
        self.fake.set_status(
            "SUB000001", "error", error_code=2, report={"totalErrors": 1}
        )
        self.poller.run_pass()
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.ERROR)
        self.assertEqual(submission.clinvar_error_code, 2)

    def test_a_failed_report_download_is_retried_without_changing_the_status(self):
        submission = self._make()
        self.fake.set_status("SUB000001", "processed", report={"totalCount": 1})
        self.fake.report_error = ClinVarError("ClinVar returned 503", retryable=True)
        self.poller.run_pass()
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.SUBMITTED)
        self.assertIsNone(submission.summary_report)
        self.assertIsNotNone(submission.next_poll_at)

    def test_a_clinvar_error_backs_off_without_changing_the_status(self):
        submission = self._make()
        self.fake.status_error = ClinVarError("ClinVar returned 503", retryable=True)
        with mock.patch("clinvar_submission_service.polling.sentry_sdk") as sentry:
            self.poller.run_pass()
        sentry.capture_exception.assert_called_once()
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.SUBMITTED)
        assert submission.next_poll_at
        self.assertGreater(submission.next_poll_at, timezone.now())

    def test_a_429_waits_at_least_retry_after(self):
        submission = self._make()
        self.fake.status_error = ClinVarError(
            "ClinVar returned 429", retryable=True, retry_after=7200
        )
        self.poller.run_pass()
        submission.refresh_from_db()
        assert submission.next_poll_at
        self.assertGreaterEqual(
            submission.next_poll_at, timezone.now() + timedelta(seconds=7190)
        )

    def test_one_failing_submission_does_not_block_the_others(self):
        failing = self._make("SUB000001")
        working = self._make("SUB000002")
        self.fake.set_status("SUB000002", "processing")
        # SUB000001 has no status in the fake, so polling it raises KeyError.
        self.poller.run_pass()
        failing.refresh_from_db()
        working.refresh_from_db()
        self.assertEqual(failing.status, Submission.Status.SUBMITTED)
        self.assertEqual(working.status, Submission.Status.PROCESSING)
        assert failing.next_poll_at
        self.assertGreater(failing.next_poll_at, timezone.now())

    def test_send_failed_and_received_submissions_are_never_polled(self):
        for status in (Submission.Status.SEND_FAILED, Submission.Status.RECEIVED):
            self._make(clinvar_id="", status=status)
        with mock.patch.object(self.fake, "get_status") as get_status:
            self.assertEqual(self.poller.run_pass(), 0)
        get_status.assert_not_called()

    @override_settings(CSS_POLL_BATCH_SIZE=1)
    def test_takes_one_batch_per_pass(self):
        self._make("SUB000001")
        self._make("SUB000002")
        self.fake.set_status("SUB000001", "processing")
        self.fake.set_status("SUB000002", "processing")
        self.assertEqual(self.poller.run_pass(), 1)

    def test_stopping_finishes_the_current_submission_first(self):
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
        submission = Submission.objects.create(
            payload={},
            status=Submission.Status.SUBMITTED,
            clinvar_submission_id="SUB000001",
            next_poll_at=timezone.now(),
        )
        self.fake.set_status("SUB000001", "processing")
        call_command("poll_clinvar", "--once")
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.PROCESSING)

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
