import importlib
import os
import sys
from datetime import timedelta
from types import ModuleType
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from auth_.models import UserProfile
from clinvar_submission_service import simulation
from clinvar_submission_service.clients import ClinVarClient, ClinVarError
from clinvar_submission_service.content import Affiliation
from clinvar_submission_service.models import Batch, BatchRecord, Record
from clinvar_submission_service.polling import Poller
from clinvar_submission_service.services import forward_batch, make_batch, save_record
from clinvar_submission_service.simulation import SimulatedClinVarClient
from clinvar_submission_service.tests.fakes import make_record


def _batch(*tool_ids: str) -> Batch:
    """Returns a not-yet-sent batch of new waiting records with the tool IDs."""
    records = [
        save_record(
            api_key=None,
            affiliation=Affiliation(id=10007, name="Hearing Loss VCEP"),
            payload=make_record(tool_id),
        )[0]
        for tool_id in tool_ids
    ]
    return make_batch(records)


class FromSettingsTest(TestCase):
    @override_settings(CSS_SIMULATE_CLINVAR=True, CSS_CLINVAR_API_KEY="")
    def test_returns_the_simulator_when_the_flag_is_on(self):
        self.assertIsInstance(ClinVarClient.from_settings(), SimulatedClinVarClient)

    @override_settings(CSS_SIMULATE_CLINVAR=False, CSS_CLINVAR_API_KEY="key")
    def test_returns_the_real_client_when_the_flag_is_off(self):
        client = ClinVarClient.from_settings()
        self.assertNotIsInstance(client, SimulatedClinVarClient)

    def test_the_flag_is_off_by_default(self):
        self.assertFalse(settings.CSS_SIMULATE_CLINVAR)


class SubmitTest(TestCase):
    def test_returns_a_new_clinvar_id_each_time(self):
        client = SimulatedClinVarClient()
        with mock.patch.object(simulation, "SEND_FAILURE_RATE", 0):
            ids = {client.submit({"germlineSubmission": []}) for _ in range(20)}
        self.assertEqual(len(ids), 20)
        for clinvar_id in ids:
            self.assertRegex(clinvar_id or "", r"^SUB\d{7}$")

    def test_sometimes_fails_so_resend_can_be_tried(self):
        client = SimulatedClinVarClient()
        with (
            mock.patch.object(simulation, "SEND_FAILURE_RATE", 1),
            self.assertRaises(ClinVarError) as raised,
        ):
            client.submit({"germlineSubmission": []})
        self.assertTrue(raised.exception.retryable)

    def test_a_dry_run_returns_no_id(self):
        self.assertIsNone(SimulatedClinVarClient().submit({}, dry_run=True))


@override_settings(CSS_SIMULATE_CLINVAR=True)
class StatusTest(TestCase):
    def setUp(self):
        patcher = mock.patch.object(simulation, "SEND_FAILURE_RATE", 0)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.client_ = SimulatedClinVarClient()

    def _sent(self, *tool_ids: str) -> Batch:
        return forward_batch(_batch(*tool_ids))

    def test_each_poll_moves_the_batch_one_step(self):
        batch = self._sent("var-1", "var-2")
        self.assertEqual(batch.status, Batch.Status.SUBMITTED_TO_CLINVAR)
        status = self.client_.get_status(batch.clinvar_submission_id)
        self.assertEqual(status.status, "processing")
        self.assertEqual(status.summary_report_url, "")
        batch.status = Batch.Status.PROCESSING_AT_CLINVAR
        batch.save()
        status = self.client_.get_status(batch.clinvar_submission_id)
        self.assertIn(status.status, {"processed", "error"})
        self.assertEqual(
            status.summary_report_url, f"simulated://{batch.clinvar_submission_id}"
        )

    def test_the_error_code_says_whether_some_or_all_records_failed(self):
        batch = self._sent("var-1", "var-2", "var-3")
        Batch.objects.filter(pk=batch.pk).update(
            status=Batch.Status.PROCESSING_AT_CLINVAR
        )
        for outcomes, status, code in [
            ([True, True, True], "processed", None),
            ([True, False, True], "error", 1),
            ([False, False, False], "error", 2),
        ]:
            with (
                self.subTest(outcomes),
                mock.patch.object(simulation, "_succeeds", side_effect=outcomes * 2),
            ):
                result = self.client_.get_status(batch.clinvar_submission_id)
                self.assertEqual((result.status, result.error_code), (status, code))

    def test_the_report_has_a_result_per_record_and_is_stable(self):
        batch = self._sent(*[f"var-{i}" for i in range(20)])
        url = f"simulated://{batch.clinvar_submission_id}"
        report = self.client_.get_summary_report(url)
        self.assertEqual(report, self.client_.get_summary_report(url))
        results = report["submissions"]
        self.assertEqual(
            [r["identifiers"]["localID"] for r in results],
            [f"var-{i}" for i in range(20)],
        )
        self.assertEqual(report["totalCount"], 20)
        for result in results:
            if result["processingStatus"] == "Success":
                self.assertRegex(
                    result["identifiers"]["clinvarAccession"], r"^SCV\d{9}$"
                )
            else:
                self.assertEqual(result["processingStatus"], "Error")
                message = result["errors"][0]["output"]["errors"][0]["userMessage"]
                self.assertTrue(message)
        successes = sum(r["processingStatus"] == "Success" for r in results)
        self.assertEqual(report["totalSuccess"], successes)
        self.assertEqual(report["totalErrors"], 20 - successes)

    def test_the_poller_and_results_work_against_it_end_to_end(self):
        batch = self._sent(*[f"var-{i}" for i in range(10)])
        poller = Poller(self.client_)
        for _ in range(2):
            Batch.objects.filter(pk=batch.pk).update(next_poll_at=batch.added_at)
            poller.run_pass()
        batch.refresh_from_db()
        self.assertIn(
            batch.status,
            {Batch.Status.PROCESSED_BY_CLINVAR, Batch.Status.ERROR_AT_CLINVAR},
        )
        self.assertIsNone(batch.next_poll_at)
        attempts = BatchRecord.objects.filter(batch=batch).select_related("record")
        for attempt in attempts:
            with self.subTest(attempt.record.tool_id):
                self.assertIn(attempt.result, {"Success", "Error"})
                expected = (
                    Record.Status.SUCCEEDED_AT_CLINVAR
                    if attempt.result == "Success"
                    else Record.Status.WAITING_FOR_BATCH
                )
                self.assertEqual(attempt.record.status, expected)


BANNER = "ClinVar is simulated."


class FirstPollTest(TestCase):
    @override_settings(CSS_FIRST_POLL_DELAY=timedelta(seconds=10))
    def test_the_first_poll_waits_the_configured_delay(self):
        with (
            mock.patch.object(simulation, "SEND_FAILURE_RATE", 0),
            override_settings(CSS_SIMULATE_CLINVAR=True),
        ):
            before = timezone.now()
            batch = forward_batch(_batch("var-1"))
        assert batch.next_poll_at is not None
        delay = batch.next_poll_at - before
        self.assertGreaterEqual(delay, timedelta(seconds=10))
        self.assertLess(delay, timedelta(seconds=15))


class BannerTest(TestCase):
    def setUp(self):
        user = User.objects.create_user(username="staff@example.com")
        UserProfile.objects.create(user=user, has_css_permissions=True)
        self.client.force_login(user)
        self.batch = _batch("var-1")
        self.record = self.batch.records.get()

    def urls(self) -> list[str]:
        return [
            reverse("css:records"),
            reverse("css:batches"),
            reverse("css:affiliations"),
            self.record.get_absolute_url(),
            self.batch.get_absolute_url(),
            reverse("css:new_batch", kwargs={"affiliation_id": 10007}),
            reverse("css:affiliation_settings", kwargs={"affiliation_id": 10007}),
        ]

    def test_every_page_says_clinvar_is_simulated_when_it_is(self):
        with override_settings(CSS_SIMULATE_CLINVAR=True):
            for url in self.urls():
                with self.subTest(url):
                    self.assertContains(self.client.get(url), BANNER)

    def test_no_page_says_so_when_it_isnt(self):
        for url in self.urls():
            with self.subTest(url):
                self.assertNotContains(self.client.get(url), BANNER)


class DevSettingsTest(TestCase):
    def _dev_settings(self, flag: str) -> ModuleType:
        with mock.patch.dict(os.environ, {"CSS_SIMULATE_CLINVAR": flag}):
            sys.modules.pop("config.settings.dev", None)
            try:
                return importlib.import_module("config.settings.dev")
            finally:
                sys.modules.pop("config.settings.dev", None)

    def test_simulating_shortens_the_poll_delays(self):
        dev = self._dev_settings("1")
        self.assertTrue(dev.CSS_SIMULATE_CLINVAR)
        self.assertEqual(dev.CSS_FIRST_POLL_DELAY, timedelta(seconds=10))
        self.assertEqual(dev.CSS_POLL_MIN_DELAY, timedelta(seconds=10))
        self.assertEqual(dev.CSS_POLL_MAX_DELAY, timedelta(minutes=1))
        self.assertEqual(dev.CSS_POLL_SLEEP_SECONDS, 5)

    def test_without_simulating_the_delays_stay_long(self):
        dev = self._dev_settings("")
        self.assertFalse(dev.CSS_SIMULATE_CLINVAR)
        self.assertEqual(dev.CSS_FIRST_POLL_DELAY, timedelta(minutes=5))
        self.assertEqual(dev.CSS_POLL_MIN_DELAY, timedelta(minutes=5))


class DeleteAllTest(TestCase):
    def setUp(self):
        user = User.objects.create_user(username="staff@example.com")
        UserProfile.objects.create(user=user, has_css_permissions=True)
        self.client.force_login(user)
        self.batch = _batch("var-1", "var-2")
        self.waiting = save_record(
            api_key=None,
            affiliation=Affiliation(id=10007, name="Hearing Loss VCEP"),
            payload=make_record("var-3"),
        )[0]

    @override_settings(CSS_SIMULATE_CLINVAR=True)
    def test_deleting_records_deletes_every_record_and_batch(self):
        response = self.client.post(reverse("css:delete_records"), follow=True)
        self.assertRedirects(response, reverse("css:records"))
        self.assertContains(response, "Deleted 3 records and every batch.")
        self.assertFalse(Record.objects.exists())
        self.assertFalse(Batch.objects.exists())
        self.assertFalse(BatchRecord.objects.exists())

    @override_settings(CSS_SIMULATE_CLINVAR=True)
    def test_deleting_batches_puts_their_records_back_to_waiting(self):
        succeeded = self.batch.records.get(tool_id="var-2")
        succeeded.status = Record.Status.SUCCEEDED_AT_CLINVAR
        succeeded.save()
        response = self.client.post(reverse("css:delete_batches"), follow=True)
        self.assertRedirects(response, reverse("css:batches"))
        self.assertContains(response, "Deleted 1 batches.")
        self.assertFalse(Batch.objects.exists())
        self.assertFalse(BatchRecord.objects.exists())
        statuses = dict(Record.objects.values_list("tool_id", "status"))
        self.assertEqual(
            statuses,
            {
                "var-1": Record.Status.WAITING_FOR_BATCH,
                "var-2": Record.Status.SUCCEEDED_AT_CLINVAR,
                "var-3": Record.Status.WAITING_FOR_BATCH,
            },
        )
        record = Record.objects.get(tool_id="var-1")
        self.assertEqual(
            record.history.first().history_change_reason,  # type: ignore
            "Its batch was deleted.",
        )

    def test_both_are_404_unless_simulating(self):
        for name in ["css:delete_records", "css:delete_batches"]:
            with self.subTest(name):
                self.assertEqual(self.client.post(reverse(name)).status_code, 404)
        self.assertEqual(Record.objects.count(), 3)
        self.assertTrue(Batch.objects.exists())

    @override_settings(CSS_SIMULATE_CLINVAR=True)
    def test_both_need_a_post(self):
        for name in ["css:delete_records", "css:delete_batches"]:
            with self.subTest(name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 405)
        self.assertEqual(Record.objects.count(), 3)

    @override_settings(CSS_SIMULATE_CLINVAR=True)
    def test_both_need_css_permissions(self):
        self.client.force_login(User.objects.create_user(username="other@example.com"))
        for name in ["css:delete_records", "css:delete_batches"]:
            with self.subTest(name):
                self.assertEqual(self.client.post(reverse(name)).status_code, 403)
        self.assertEqual(Record.objects.count(), 3)

    def test_the_banner_shows_the_buttons_only_while_simulating(self):
        url = reverse("css:records")
        with override_settings(CSS_SIMULATE_CLINVAR=True):
            response = self.client.get(url)
        self.assertContains(response, reverse("css:delete_records"))
        self.assertContains(response, reverse("css:delete_batches"))
        self.assertContains(response, "Flush Records")
        self.assertContains(response, "Flush Batches")
        self.assertContains(response, 'data-confirm="Delete every record and batch?"')
        response = self.client.get(url)
        self.assertNotContains(response, reverse("css:delete_records"))
        self.assertNotContains(response, reverse("css:delete_batches"))
