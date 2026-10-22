import importlib
import uuid
from datetime import datetime, timedelta

from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from auth_.models import UserProfile
from clinvar_submission_service.models import (
    AffectedStatus,
    AlleleOrigin,
    Assembly,
    Classification,
    CollectionMethod,
    ConditionDb,
    Record,
    RecordStatus,
    Submission,
)
from common.models import make_slug


def _make_user(username: str, *, css: bool = False) -> User:
    """Returns a user whose profile has the given CSS permission."""
    user = User.objects.create_user(username=username, email=username)
    UserProfile.objects.create(user=user, has_css_permissions=css)
    return user


class SubmissionTest(TestCase):
    def test_slug_is_s_and_the_start_of_the_uuid(self):
        submission = Submission.objects.create(payload={})
        self.assertEqual(submission.slug, f"S{submission.pk.hex[:8]}")
        self.assertEqual(str(submission), submission.slug)

    def test_slug_does_not_change_on_later_saves(self):
        submission = Submission.objects.create(payload={})
        slug = submission.slug
        submission.status = Submission.Status.SUBMITTED_TO_CLINVAR
        submission.save()
        submission.refresh_from_db()
        self.assertEqual(submission.slug, slug)

    def test_colliding_slug_gets_a_new_uuid(self):
        taken = Submission.objects.create(
            id=uuid.UUID("3f2a9c1e-0000-4000-8000-000000000000"), payload={}
        )
        # Same first 8 hex characters as the taken one, so the slug collides.
        colliding = uuid.UUID("3f2a9c1e-ffff-4fff-8fff-ffffffffffff")
        submission = Submission.objects.create(id=colliding, payload={})
        self.assertNotEqual(submission.pk, colliding)
        self.assertNotEqual(submission.slug, taken.slug)

    def test_new_submission_is_not_sent_to_clinvar(self):
        submission = Submission.objects.create(payload={})
        self.assertEqual(submission.status, Submission.Status.NOT_SENT_TO_CLINVAR)

    def test_history_records_status_change(self):
        submission = Submission.objects.create(payload={})
        submission.status = Submission.Status.SUBMITTED_TO_CLINVAR
        submission.save()
        records = submission.history.order_by("history_date")  # type: ignore
        statuses = list(records.values_list("status", flat=True))
        self.assertEqual(statuses, ["not_sent_to_clinvar", "submitted_to_clinvar"])


def _make_record(
    submission: Submission | None, local_id: str, **fields: object
) -> Record:
    """Returns a likely pathogenic record, in the submission if one is given."""
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
    return Record.objects.create(submission=submission, **(defaults | fields))


class RecordTest(TestCase):
    def setUp(self):
        self.submission = Submission.objects.create(payload={})

    def test_belongs_to_a_submission_in_local_id_order(self):
        second = _make_record(self.submission, "var-2")
        first = _make_record(self.submission, "var-1")
        self.assertEqual(list(self.submission.records.all()), [first, second])  # type: ignore

    def test_string_representation_is_the_variant_and_classification(self):
        record = _make_record(self.submission, "var-1")
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
        record = _make_record(self.submission, "var-1")
        record.classification = Classification.PATHOGENIC
        record.save()
        classifications = record.history.order_by("history_date").values_list(  # type: ignore
            "classification", flat=True
        )
        self.assertEqual(list(classifications), ["Likely pathogenic", "Pathogenic"])

    def test_deleting_the_submission_deletes_its_records(self):
        _make_record(self.submission, "var-1")
        self.submission.delete()
        self.assertFalse(Record.objects.exists())


class StandaloneRecordTest(TestCase):
    def test_slug_is_r_and_the_start_of_its_uuid(self):
        record = _make_record(None, "var-1")
        self.assertEqual(record.slug, make_slug("R", record.pk))

    def test_a_new_record_waits_for_a_batch_outside_any_submission(self):
        record = _make_record(None, "var-1")
        self.assertIsNone(record.submission)
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
    def _make(self, status: str, next_poll_at: datetime | None) -> Submission:
        return Submission.objects.create(
            payload={}, status=status, next_poll_at=next_poll_at
        )

    def test_returns_only_non_final_submissions_that_are_due(self):
        past = timezone.now() - timedelta(hours=1)
        future = timezone.now() + timedelta(hours=1)
        due_submitted = self._make(Submission.Status.SUBMITTED_TO_CLINVAR, past)
        due_processing = self._make(Submission.Status.PROCESSING_AT_CLINVAR, past)
        self._make(Submission.Status.SUBMITTED_TO_CLINVAR, future)
        self._make(Submission.Status.PROCESSING_AT_CLINVAR, None)
        for status in (
            Submission.Status.NOT_SENT_TO_CLINVAR,
            Submission.Status.SEND_TO_CLINVAR_FAILED,
            Submission.Status.PROCESSED_BY_CLINVAR,
            Submission.Status.ERROR_AT_CLINVAR,
        ):
            self._make(status, past)
        self.assertQuerySetEqual(
            Submission.objects.due_to_poll(),
            [due_submitted, due_processing],
            ordered=False,
        )


class SubmissionAdminTest(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser(username="admin"))
        self.submission = Submission.objects.create(payload={"records": []})

    def test_list_page_renders(self):
        url = reverse("admin:clinvar_submission_service_submission_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.submission.slug)

    def test_change_page_renders(self):
        url = reverse(
            "admin:clinvar_submission_service_submission_change",
            args=[self.submission.pk],
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_change_page_lists_the_records(self):
        _make_record(self.submission, "var-1")
        url = reverse(
            "admin:clinvar_submission_service_submission_change",
            args=[self.submission.pk],
        )
        response = self.client.get(url)
        self.assertContains(response, "var-1")
        self.assertContains(response, "NC_000017.11:g.43045712T&gt;C")


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


class StatusMigrationTest(TestCase):
    """The migration that names each status relative to ClinVar."""

    migration = importlib.import_module(
        "clinvar_submission_service.migrations.0005_status_relative_to_clinvar"
    )

    def _set_raw_status(self, submission: Submission, status: str) -> None:
        """Gives the submission and its history a status as an old row had it."""
        Submission.objects.filter(pk=submission.pk).update(status=status)
        submission.history.update(status=status)  # type: ignore

    def test_renames_every_old_status_and_back(self):
        for old, new in self.migration.RENAMES.items():
            with self.subTest(old=old):
                submission = Submission.objects.create(payload={})
                self._set_raw_status(submission, old)
                self.migration.rename_statuses(apps, None)
                submission.refresh_from_db()
                self.assertEqual(submission.status, new)
                history = submission.history.values_list("status", flat=True)  # type: ignore
                self.assertEqual(set(history), {new})
                self.migration.restore_statuses(apps, None)
                submission.refresh_from_db()
                self.assertEqual(submission.status, old)

    def test_renames_to_the_current_statuses(self):
        self.assertEqual(
            set(self.migration.RENAMES.values()), set(Submission.Status.values)
        )
