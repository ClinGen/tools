from unittest import mock

from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase

from clinvar_submission_service.clients import ClinVarError
from clinvar_submission_service.content import Affiliation
from clinvar_submission_service.fakes import FakeClinVarClient, make_record
from clinvar_submission_service.models import AffiliationSettings, Batch, Record
from clinvar_submission_service.services import (
    BatchNotMadeError,
    build_payload,
    forward_batch,
    make_batch,
    save_record,
)

HEARING_LOSS = Affiliation(id=10007, name="Hearing Loss VCEP")


def _waiting(local_id: str, affiliation: Affiliation = HEARING_LOSS) -> Record:
    record, _ = save_record(
        api_key=None, affiliation=affiliation, payload=make_record(local_id)
    )
    return record


class ServicesTestCase(TestCase):
    def setUp(self):
        self.fake = FakeClinVarClient()
        patcher = mock.patch(
            "clinvar_submission_service.services.ClinVarClient.from_settings",
            return_value=self.fake,
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class MakeBatchTest(ServicesTestCase):
    def test_makes_a_batch_from_one_affiliations_waiting_records(self):
        first, second = _waiting("var-2"), _waiting("var-1")
        batch = make_batch([first, second])
        self.assertEqual(batch.status, Batch.Status.NOT_SENT_TO_CLINVAR)
        self.assertEqual(batch.affiliation_id, 10007)
        self.assertEqual(batch.affiliation_name, "Hearing Loss VCEP")
        self.assertEqual(list(batch.records.order_by("batch_records")), [first, second])
        for record in (first, second):
            record.refresh_from_db()
            self.assertEqual(record.status, Record.Status.IN_BATCH)

    def test_copies_the_affiliations_settings(self):
        AffiliationSettings.objects.create(
            affiliation_id=10007,
            assertion_criteria_db="PubMed",
            assertion_criteria_id="25741868",
            behalf_org_id=506185,
            release_status="hold until published",
        )
        batch = make_batch([_waiting("var-1")])
        self.assertEqual(
            build_payload(batch),
            {
                "germlineSubmission": [make_record("var-1")],
                "assertionCriteria": {"db": "PubMed", "id": "25741868"},
                "behalfOrgID": 506185,
                "clinvarSubmissionReleaseStatus": "hold until published",
            },
        )

    def test_without_settings_leaves_the_submission_fields_out(self):
        batch = make_batch([_waiting("var-1")])
        self.assertEqual(
            build_payload(batch), {"germlineSubmission": [make_record("var-1")]}
        )

    def test_refuses_records_it_cant_batch_and_saves_nothing(self):
        other = Affiliation(id=10008, name="Cardiomyopathy VCEP")
        cases = {
            "no records": ([], "Pick at least one record."),
            "mixed affiliations": (
                [_waiting("a"), _waiting("b", other)],
                "A batch can hold only one affiliation's records.",
            ),
            "withdrawn": (
                [_waiting("c"), _waiting("d")],
                "Only records waiting for a batch can be added to one.",
            ),
            "already batched": (
                [_waiting("e"), make_batch([_waiting("f")]).records.get()],
                "Only records waiting for a batch can be added to one.",
            ),
        }
        Record.objects.filter(local_id="d").update(status=Record.Status.WITHDRAWN)
        batches_before = Batch.objects.count()
        for name, (records, message) in cases.items():
            with self.subTest(name):
                with self.assertRaisesMessage(BatchNotMadeError, message):
                    make_batch(records)
                self.assertEqual(Batch.objects.count(), batches_before)
        self.assertEqual(
            Record.objects.get(local_id="a").status, Record.Status.WAITING_FOR_BATCH
        )

    def test_refuses_more_records_than_clinvar_takes(self):
        records = [_waiting("var-1"), _waiting("var-2")]
        with (
            mock.patch("clinvar_submission_service.services.MAX_RECORDS", 1),
            self.assertRaisesMessage(
                BatchNotMadeError, "A batch can hold at most 1 records."
            ),
        ):
            make_batch(records)


class ForwardBatchTest(ServicesTestCase):
    def setUp(self):
        super().setUp()
        self.records = [_waiting("var-1"), _waiting("var-2")]
        self.batch = make_batch(self.records)

    def test_sending_a_batch_sends_its_records_and_keeps_them_in_it(self):
        forward_batch(self.batch)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, Batch.Status.SUBMITTED_TO_CLINVAR)
        self.assertEqual(self.batch.clinvar_submission_id, "SUB000001")
        self.assertIsNotNone(self.batch.next_poll_at)
        self.assertEqual(
            self.fake.submitted,
            [{"germlineSubmission": [make_record("var-1"), make_record("var-2")]}],
        )
        for record in self.records:
            record.refresh_from_db()
            self.assertEqual(record.status, Record.Status.IN_BATCH)

    def test_a_send_failure_keeps_the_records_in_the_batch_to_resend(self):
        self.fake.submit_error = ClinVarError("ClinVar returned 400", retryable=False)
        forward_batch(self.batch)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, Batch.Status.SEND_TO_CLINVAR_FAILED)
        self.assertEqual(self.batch.error_message, "ClinVar returned 400")
        self.assertEqual(self.batch.clinvar_submission_id, "")
        self.assertEqual(self.batch.records.count(), 2)
        self.assertEqual(
            set(self.batch.records.values_list("status", flat=True)),
            {Record.Status.IN_BATCH},
        )
        self.fake.submit_error = None
        forward_batch(self.batch)
        self.assertEqual(self.batch.status, Batch.Status.SUBMITTED_TO_CLINVAR)

    def test_a_failed_send_is_not_retried(self):
        self.fake.submit_error = ClinVarError("ClinVar returned 503", retryable=True)
        with mock.patch.object(self.fake, "submit", wraps=self.fake.submit) as submit:
            forward_batch(self.batch)
        submit.assert_called_once()

    def test_an_unconfigured_client_is_send_failed(self):
        with mock.patch(
            "clinvar_submission_service.services.ClinVarClient.from_settings",
            side_effect=ImproperlyConfigured("Set CSS_CLINVAR_API_KEY."),
        ):
            forward_batch(self.batch)
        self.batch.refresh_from_db()
        self.assertEqual(self.batch.status, Batch.Status.SEND_TO_CLINVAR_FAILED)
