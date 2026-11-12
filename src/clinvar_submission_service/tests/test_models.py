import uuid
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone

from clinvar_submission_service.models import (
    AffiliationSettings,
    Batch,
    BatchRecord,
    Classification,
    Record,
)
from clinvar_submission_service.tests.fakes import make_saved_record
from common.models import make_slug


class SubmissionTest(TestCase):
    def test_slug_is_b_and_the_start_of_the_uuid(self):
        batch = Batch.objects.create()
        self.assertEqual(batch.slug, f"B{batch.pk.hex[:8]}")
        self.assertEqual(str(batch), batch.slug)

    def test_slug_does_not_change_on_later_saves(self):
        batch = Batch.objects.create()
        slug = batch.slug
        batch.status = Batch.Status.SUBMITTED_TO_CLINVAR
        batch.save()
        batch.refresh_from_db()
        self.assertEqual(batch.slug, slug)

    def test_colliding_slug_gets_a_new_uuid(self):
        taken = Batch.objects.create(
            id=uuid.UUID("3f2a9c1e-0000-4000-8000-000000000000")
        )
        # Same first 8 hex characters as the taken one, so the slug collides.
        colliding = uuid.UUID("3f2a9c1e-ffff-4fff-8fff-ffffffffffff")
        batch = Batch.objects.create(id=colliding)
        self.assertNotEqual(batch.pk, colliding)
        self.assertNotEqual(batch.slug, taken.slug)

    def test_new_batch_is_not_sent_to_clinvar(self):
        batch = Batch.objects.create()
        self.assertEqual(batch.status, Batch.Status.NOT_SENT_TO_CLINVAR)

    def test_history_records_status_change(self):
        batch = Batch.objects.create()
        batch.status = Batch.Status.SUBMITTED_TO_CLINVAR
        batch.save()
        records = batch.history.order_by("history_date")  # type: ignore
        statuses = list(records.values_list("status", flat=True))
        self.assertEqual(statuses, ["not_sent_to_clinvar", "submitted_to_clinvar"])


class RecordTest(TestCase):
    def setUp(self):
        self.batch = Batch.objects.create()

    def test_a_batchs_records_are_in_the_order_they_were_added(self):
        second = make_saved_record(self.batch, "var-2")
        first = make_saved_record(self.batch, "var-1")
        attempts = self.batch.batch_records.all()  # type: ignore
        self.assertEqual([attempt.record for attempt in attempts], [second, first])

    def test_string_representation_is_the_variant_and_classification(self):
        record = make_saved_record(self.batch, "var-1")
        self.assertEqual(str(record), "NC_000017.11:g.43045712T>C: Likely pathogenic")

    def test_classifications_are_clinvars_acmg_terms(self):
        self.assertEqual(
            Classification.values,
            [
                "Pathogenic",
                "Likely pathogenic",
                "Uncertain significance",
                "Likely benign",
                "Benign",
            ],
        )

    def test_history_records_a_change(self):
        record = make_saved_record(self.batch, "var-1")
        record.classification = Classification.PATHOGENIC
        record.save()
        classifications = record.history.order_by("history_date").values_list(  # type: ignore
            "classification", flat=True
        )
        self.assertEqual(list(classifications), ["Likely pathogenic", "Pathogenic"])

    def test_deleting_a_batch_keeps_its_records_but_not_its_attempts(self):
        record = make_saved_record(self.batch, "var-1")
        self.batch.delete()
        self.assertTrue(Record.objects.filter(pk=record.pk).exists())
        self.assertFalse(BatchRecord.objects.exists())


class BatchRecordTest(TestCase):
    def test_a_record_is_in_a_batch_once(self):
        batch = Batch.objects.create()
        record = make_saved_record(batch, "var-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            BatchRecord.objects.create(batch=batch, record=record, position=1)

    def test_a_record_can_be_tried_in_several_batches(self):
        first, second = Batch.objects.create(), Batch.objects.create()
        record = make_saved_record(first, "var-1")
        BatchRecord.objects.create(batch=second, record=record, position=0)
        self.assertEqual(set(record.batches.all()), {first, second})  # type: ignore

    def test_an_attempt_starts_with_no_result_and_keeps_history(self):
        batch = Batch.objects.create()
        make_saved_record(batch, "var-1")
        attempt = BatchRecord.objects.get()
        self.assertEqual((attempt.result, attempt.scv, attempt.errors), ("", "", None))
        attempt.result = BatchRecord.Result.SUCCESS
        attempt.save()
        self.assertEqual(attempt.history.count(), 2)  # type: ignore


class StandaloneRecordTest(TestCase):
    def test_slug_is_r_and_the_start_of_its_uuid(self):
        record = make_saved_record(None, "var-1")
        self.assertEqual(record.slug, make_slug("R", record.pk))

    def test_a_new_record_waits_for_a_batch_outside_any_batch(self):
        record = make_saved_record(None, "var-1")
        self.assertFalse(record.batches.exists())  # type: ignore
        self.assertEqual(record.status, Record.Status.WAITING_FOR_BATCH)

    def test_history_records_a_status_change(self):
        record = make_saved_record(None, "var-1")
        record.status = Record.Status.WITHDRAWN
        record.save()
        statuses = record.history.order_by("history_date").values_list(  # type: ignore
            "status", flat=True
        )
        self.assertEqual(list(statuses), ["waiting_for_batch", "withdrawn"])

    def test_bulk_slugs_avoid_saved_and_repeated_ones(self):
        taken = make_saved_record(None, "var-1")
        # Same first 8 hex characters as the saved record and as each other.
        prefix = taken.pk.hex[:8]
        records = [
            Record(id=uuid.UUID(f"{prefix}-0000-4000-8000-{n:012x}"), local_id=f"v{n}")
            for n in range(1, 4)
        ]
        Record.set_unique_slugs(records)
        slugs = [record.slug for record in records]
        self.assertEqual(len(set(slugs)), 3)
        self.assertNotIn(taken.slug, slugs)
        for record in records:
            self.assertEqual(record.slug, make_slug("R", record.pk))

    def test_every_status_has_help_for_its_tooltip(self):
        for status in Record.Status.values:
            with self.subTest(status=status):
                record = Record(status=status)
                self.assertTrue(record.status_help)
                self.assertEqual(record.status_help, Record.STATUS_HELP[status])

    def test_every_status_names_where_the_record_is(self):
        self.assertEqual(
            Record.Status.values,
            [
                "waiting_for_batch",
                "in_batch",
                "succeeded_at_clinvar",
                "withdrawn",
            ],
        )


class AffiliationSettingsTest(TestCase):
    def test_saves_an_affiliations_settings_and_keeps_history(self):
        settings = AffiliationSettings.objects.create(
            affiliation_id=10007,
            assertion_criteria_db="PubMed",
            assertion_criteria_id="25741868",
            behalf_org_id=506185,
            release_status="public",
        )
        settings.release_status = "hold until published"
        settings.save()
        settings.refresh_from_db()
        self.assertEqual(settings.assertion_criteria_db, "PubMed")
        self.assertEqual(settings.behalf_org_id, 506185)
        statuses = settings.history.order_by("history_date").values_list(  # type: ignore
            "release_status", flat=True
        )
        self.assertEqual(list(statuses), ["public", "hold until published"])

    def test_an_affiliation_has_one_set_of_settings(self):
        AffiliationSettings.objects.create(affiliation_id=10007)
        with self.assertRaises(IntegrityError), transaction.atomic():
            AffiliationSettings.objects.create(affiliation_id=10007)


class DueToPollTest(TestCase):
    def _make(self, status: str, next_poll_at: datetime | None) -> Batch:
        return Batch.objects.create(status=status, next_poll_at=next_poll_at)

    def test_returns_only_non_final_submissions_that_are_due(self):
        past = timezone.now() - timedelta(hours=1)
        future = timezone.now() + timedelta(hours=1)
        due_submitted = self._make(Batch.Status.SUBMITTED_TO_CLINVAR, past)
        due_processing = self._make(Batch.Status.PROCESSING_AT_CLINVAR, past)
        self._make(Batch.Status.SUBMITTED_TO_CLINVAR, future)
        self._make(Batch.Status.PROCESSING_AT_CLINVAR, None)
        for status in (
            Batch.Status.NOT_SENT_TO_CLINVAR,
            Batch.Status.SEND_TO_CLINVAR_FAILED,
            Batch.Status.PROCESSED_BY_CLINVAR,
            Batch.Status.ERROR_AT_CLINVAR,
        ):
            self._make(status, past)
        self.assertQuerySetEqual(
            Batch.objects.due_to_poll(),
            [due_submitted, due_processing],
            ordered=False,
        )
