from unittest import mock

from django.conf import settings
from django.test import TestCase, override_settings

from clinvar_submission_service import simulation
from clinvar_submission_service.clients import ClinVarClient, ClinVarError
from clinvar_submission_service.content import Affiliation
from clinvar_submission_service.fakes import make_record
from clinvar_submission_service.models import Batch, BatchRecord, Record
from clinvar_submission_service.polling import Poller
from clinvar_submission_service.services import forward_batch, make_batch, save_record
from clinvar_submission_service.simulation import SimulatedClinVarClient


def _batch(*local_ids: str) -> Batch:
    """Returns a not-yet-sent batch of new waiting records with the local IDs."""
    records = [
        save_record(
            api_key=None,
            affiliation=Affiliation(id=10007, name="Hearing Loss VCEP"),
            payload=make_record(local_id),
        )[0]
        for local_id in local_ids
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

    def _sent(self, *local_ids: str) -> Batch:
        return forward_batch(_batch(*local_ids))

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
            with self.subTest(attempt.record.local_id):
                self.assertIn(attempt.result, {"Success", "Error"})
                expected = (
                    Record.Status.SUCCEEDED_AT_CLINVAR
                    if attempt.result == "Success"
                    else Record.Status.WAITING_FOR_BATCH
                )
                self.assertEqual(attempt.record.status, expected)
