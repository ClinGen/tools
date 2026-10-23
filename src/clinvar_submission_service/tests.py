import importlib
import uuid
from datetime import datetime, timedelta
from typing import ClassVar

from django.apps import apps
from django.contrib.auth.models import User
from django.db import IntegrityError, models, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from auth_.models import UserProfile
from clinvar_submission_service.models import (
    AffectedStatus,
    AlleleOrigin,
    Assembly,
    Batch,
    BatchRecord,
    Classification,
    CollectionMethod,
    ConditionDb,
    Record,
    RecordStatus,
)
from clinvar_submission_service.services import build_payload
from common.models import make_slug


def _make_user(username: str, *, css: bool = False) -> User:
    """Returns a user whose profile has the given CSS permission."""
    user = User.objects.create_user(username=username, email=username)
    UserProfile.objects.create(user=user, has_css_permissions=css)
    return user


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


def _make_record(batch: Batch | None, local_id: str, **fields: object) -> Record:
    """Returns a likely pathogenic record, in the batch if one is given."""
    defaults = {
        "record_status": RecordStatus.NOVEL,
        "local_id": local_id,
        "submitted_assembly": Assembly.GRCH38,
        "hgvs": "NC_000017.11:g.43045712T>C",
        "condition_db": ConditionDb.MONDO,
        "condition_id": "MONDO:0011450",
        "classification": Classification.LIKELY_PATHOGENIC,
        "allele_origin": AlleleOrigin.GERMLINE,
        "affected_status": AffectedStatus.NOT_PROVIDED,
        "collection_method": CollectionMethod.CURATION,
    }
    record = Record.objects.create(**(defaults | fields))
    if batch:
        BatchRecord.objects.create(
            batch=batch,
            record=record,
            position=batch.batch_records.count(),  # type: ignore
        )
    return record


class RecordTest(TestCase):
    def setUp(self):
        self.batch = Batch.objects.create()

    def test_a_batchs_records_are_in_the_order_they_were_added(self):
        second = _make_record(self.batch, "var-2")
        first = _make_record(self.batch, "var-1")
        attempts = self.batch.batch_records.all()  # type: ignore
        self.assertEqual([attempt.record for attempt in attempts], [second, first])

    def test_string_representation_is_the_variant_and_classification(self):
        record = _make_record(self.batch, "var-1")
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
        record = _make_record(self.batch, "var-1")
        record.classification = Classification.PATHOGENIC
        record.save()
        classifications = record.history.order_by("history_date").values_list(  # type: ignore
            "classification", flat=True
        )
        self.assertEqual(list(classifications), ["Likely pathogenic", "Pathogenic"])

    def test_deleting_a_batch_keeps_its_records_but_not_its_attempts(self):
        record = _make_record(self.batch, "var-1")
        self.batch.delete()
        self.assertTrue(Record.objects.filter(pk=record.pk).exists())
        self.assertFalse(BatchRecord.objects.exists())


class BatchRecordTest(TestCase):
    def test_a_record_is_in_a_batch_once(self):
        batch = Batch.objects.create()
        record = _make_record(batch, "var-1")
        with self.assertRaises(IntegrityError), transaction.atomic():
            BatchRecord.objects.create(batch=batch, record=record, position=1)

    def test_a_record_can_be_tried_in_several_batches(self):
        first, second = Batch.objects.create(), Batch.objects.create()
        record = _make_record(first, "var-1")
        BatchRecord.objects.create(batch=second, record=record, position=0)
        self.assertEqual(set(record.batches.all()), {first, second})  # type: ignore

    def test_an_attempt_starts_with_no_result_and_keeps_history(self):
        batch = Batch.objects.create()
        _make_record(batch, "var-1")
        attempt = BatchRecord.objects.get()
        self.assertEqual((attempt.result, attempt.scv, attempt.errors), ("", "", None))
        attempt.result = BatchRecord.Result.SUCCESS
        attempt.save()
        self.assertEqual(attempt.history.count(), 2)  # type: ignore


class BuildPayloadTest(TestCase):
    def test_lists_each_records_json_in_order_with_the_batchs_fields(self):
        batch = Batch.objects.create(
            assertion_criteria_db="PubMed",
            assertion_criteria_id="25741868",
            behalf_org_id=506185,
            release_status="public",
        )
        first = _make_record(batch, "var-2")
        second = _make_record(batch, "var-1")
        self.assertEqual(
            build_payload(batch),
            {
                "germlineSubmission": [first.payload, second.payload],
                "assertionCriteria": {"db": "PubMed", "id": "25741868"},
                "behalfOrgID": 506185,
                "clinvarSubmissionReleaseStatus": "public",
            },
        )

    def test_leaves_out_fields_the_batch_doesnt_have(self):
        batch = Batch.objects.create()
        record = _make_record(batch, "var-1")
        self.assertEqual(build_payload(batch), {"germlineSubmission": [record.payload]})


class StandaloneRecordTest(TestCase):
    def test_slug_is_r_and_the_start_of_its_uuid(self):
        record = _make_record(None, "var-1")
        self.assertEqual(record.slug, make_slug("R", record.pk))

    def test_a_new_record_waits_for_a_batch_outside_any_batch(self):
        record = _make_record(None, "var-1")
        self.assertFalse(record.batches.exists())  # type: ignore
        self.assertEqual(record.status, Record.Status.WAITING_FOR_BATCH)

    def test_history_records_a_status_change(self):
        record = _make_record(None, "var-1")
        record.status = Record.Status.WITHDRAWN
        record.save()
        statuses = record.history.order_by("history_date").values_list(  # type: ignore
            "status", flat=True
        )
        self.assertEqual(list(statuses), ["waiting_for_batch", "withdrawn"])

    def test_bulk_slugs_avoid_saved_and_repeated_ones(self):
        taken = _make_record(None, "var-1")
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


class BatchAdminTest(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser(username="admin"))
        self.batch = Batch.objects.create()

    def test_list_page_renders(self):
        url = reverse("admin:clinvar_submission_service_batch_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.batch.slug)

    def test_change_page_renders(self):
        url = reverse(
            "admin:clinvar_submission_service_batch_change",
            args=[self.batch.pk],
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_change_page_lists_the_records(self):
        _make_record(self.batch, "var-1")
        url = reverse(
            "admin:clinvar_submission_service_batch_change",
            args=[self.batch.pk],
        )
        response = self.client.get(url)
        self.assertContains(
            response, "NC_000017.11:g.43045712T&gt;C: Likely pathogenic"
        )

    def test_a_records_page_lists_its_batches(self):
        record = _make_record(self.batch, "var-1")
        url = reverse(
            "admin:clinvar_submission_service_record_change", args=[record.pk]
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.batch.slug)


class IndexViewTest(TestCase):
    def test_anonymous_user_is_sent_to_sign_in(self):
        response = self.client.get(reverse("css:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login", response["Location"])

    def test_user_without_css_permissions_gets_403(self):
        self.client.force_login(_make_user("staff@example.com"))
        response = self.client.get(reverse("css:index"))
        self.assertEqual(response.status_code, 403)

    def test_user_with_css_permissions_gets_200(self):
        self.client.force_login(_make_user("staff@example.com", css=True))
        response = self.client.get(reverse("css:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "clinvar_submission_service/list.html")
        self.assertContains(response, "ClinVar Submission Service")

    def test_landing_page_lists_the_css(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "ClinVar Submission Service")
        self.assertContains(response, reverse("css:index"))


class _RenamedModels:
    """Stands in for a migration's apps, giving today's models their old names.

    The status migration ran when Batch was called Submission.
    """

    OLD_NAMES: ClassVar[dict[str, str]] = {
        "Submission": "Batch",
        "HistoricalSubmission": "HistoricalBatch",
    }

    def get_model(self, app_label: str, model_name: str) -> type[models.Model]:
        """Returns today's model for the model's old name."""
        return apps.get_model(app_label, self.OLD_NAMES.get(model_name, model_name))


class StatusMigrationTest(TestCase):
    """The migration that names each status relative to ClinVar."""

    migration = importlib.import_module(
        "clinvar_submission_service.migrations.0005_status_relative_to_clinvar"
    )

    def _set_raw_status(self, batch: Batch, status: str) -> None:
        """Gives the batch and its history a status as an old row had it."""
        Batch.objects.filter(pk=batch.pk).update(status=status)
        batch.history.update(status=status)  # type: ignore

    def test_renames_every_old_status_and_back(self):
        for old, new in self.migration.RENAMES.items():
            with self.subTest(old=old):
                batch = Batch.objects.create()
                self._set_raw_status(batch, old)
                self.migration.rename_statuses(_RenamedModels(), None)
                batch.refresh_from_db()
                self.assertEqual(batch.status, new)
                history = batch.history.values_list("status", flat=True)  # type: ignore
                self.assertEqual(set(history), {new})
                self.migration.restore_statuses(_RenamedModels(), None)
                batch.refresh_from_db()
                self.assertEqual(batch.status, old)

    def test_renames_to_the_current_statuses(self):
        self.assertEqual(set(self.migration.RENAMES.values()), set(Batch.Status.values))
