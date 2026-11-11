import uuid

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db.models import Count
from django.test import TestCase
from django.urls import reverse

from auth_.models import UserProfile
from clinvar_submission_service.content import Content, record_fields
from clinvar_submission_service.models import ApiKey, Batch, BatchRecord, Record
from clinvar_submission_service.services import build_payload, report_results
from common.models import make_slug

# An attempt in the fixture, B84b495c1's only record.
FIXTURE_ATTEMPT = "f6a92933-a57f-4a12-9b37-7f69c903bf1e"

FORWARDED_STATUSES = {
    Batch.Status.SUBMITTED_TO_CLINVAR,
    Batch.Status.PROCESSING_AT_CLINVAR,
    Batch.Status.PROCESSED_BY_CLINVAR,
    Batch.Status.ERROR_AT_CLINVAR,
}


class FixtureTest(TestCase):
    fixtures = ["test_batches.json"]

    def test_has_a_batch_in_every_status(self):
        statuses = set(Batch.objects.values_list("status", flat=True))
        self.assertEqual(statuses, set(Batch.Status.values))

    def test_slugs_come_from_random_looking_uuids(self):
        for batch in Batch.objects.all():
            with self.subTest(batch.slug):
                self.assertEqual(batch.slug, make_slug("B", batch.pk))
                # Hand-numbered UUIDs would give slugs like B00000006.
                self.assertNotRegex(batch.slug, r"^B0000")

    def test_submissions_belong_to_several_affiliations(self):
        affiliations = set(
            Batch.objects.values_list("affiliation_id", "affiliation_name")
        )
        self.assertGreaterEqual(len(affiliations), 3)
        self.assertNotIn(None, {affiliation_id for affiliation_id, _ in affiliations})

    def test_only_forwarded_submissions_have_a_clinvar_id(self):
        for batch in Batch.objects.all():
            with self.subTest(batch.status):
                forwarded = batch.status in FORWARDED_STATUSES
                self.assertEqual(bool(batch.clinvar_submission_id), forwarded)

    def test_only_finished_submissions_have_a_summary_report(self):
        for batch in Batch.objects.all():
            with self.subTest(batch.status):
                finished = batch.status in {
                    Batch.Status.PROCESSED_BY_CLINVAR,
                    Batch.Status.ERROR_AT_CLINVAR,
                }
                self.assertEqual(batch.summary_report is not None, finished)

    def test_each_batchs_records_match_its_payload(self):
        for batch in Batch.objects.all():
            with self.subTest(batch.slug):
                payload = build_payload(batch)
                content = Content.model_validate(payload)
                attempts = batch.batch_records.select_related("record")  # type: ignore
                records = [attempt.record for attempt in attempts]
                self.assertEqual(
                    [record.payload for record in records],
                    payload["germlineSubmission"],
                )
                fields = record_fields(content)
                for record, expected in zip(records, fields, strict=True):
                    if record.status == Record.Status.SUCCEEDED_AT_CLINVAR:
                        # ClinVar gave an accepted record its SCV.
                        del expected["clinvar_accession"]
                    for name, value in expected.items():
                        self.assertEqual(getattr(record, name), value, name)
                    self.assertEqual(record.affiliation_id, batch.affiliation_id)

    def test_has_a_record_in_every_status(self):
        statuses = set(Record.objects.values_list("status", flat=True))
        self.assertEqual(statuses, set(Record.Status.values))

    def test_has_a_record_retried_across_two_batches(self):
        retried = Record.objects.annotate(tries=Count("batch_records")).filter(
            tries__gte=2
        )
        self.assertTrue(retried.exists())
        attempts = retried.first().batch_records.order_by("batch__added_at")  # type: ignore
        self.assertEqual(attempts.first().result, BatchRecord.Result.ERROR)

    def test_each_attempts_result_matches_its_batchs_report(self):
        for attempt in BatchRecord.objects.select_related("batch", "record"):
            with self.subTest(attempt):
                result = report_results(attempt.batch.summary_report).get(
                    attempt.record.local_id
                )
                self.assertEqual(
                    attempt.result, result["processingStatus"] if result else ""
                )

    def test_every_page_renders(self):
        user = User.objects.create_user(username="staff@example.com")
        UserProfile.objects.create(user=user, has_css_permissions=True)
        self.client.force_login(user)
        affiliation_ids = set(Record.objects.values_list("affiliation_id", flat=True))
        pages = [
            reverse("css:index"),
            reverse("css:records"),
            reverse("css:affiliations"),
            *(batch.get_absolute_url() for batch in Batch.objects.all()),
            *(record.get_absolute_url() for record in Record.objects.all()),
            *(
                reverse(name, kwargs={"affiliation_id": affiliation_id})
                for affiliation_id in affiliation_ids
                for name in ["css:new_batch", "css:affiliation_settings"]
            ),
        ]
        for url in pages:
            with self.subTest(url):
                self.assertEqual(self.client.get(url).status_code, 200)


class LoadSampleDataTest(TestCase):
    def test_loading_twice_resets_the_sample_data(self):
        call_command("load_css_sample_data", verbosity=0)
        counts = (Batch.objects.count(), Record.objects.count())
        call_command("load_css_sample_data", verbosity=0)
        self.assertEqual((Batch.objects.count(), Record.objects.count()), counts)

    def test_replaces_attempts_and_data_made_in_the_ui(self):
        call_command("load_css_sample_data", verbosity=0)
        # As migration 0008 left them: the same attempts under other IDs.
        for attempt in BatchRecord.objects.all():
            BatchRecord.objects.filter(pk=attempt.pk).update(id=uuid.uuid4())
        made_in_ui = Batch.objects.create(affiliation_id=10901)
        call_command("load_css_sample_data", verbosity=0)
        self.assertFalse(Batch.objects.filter(pk=made_in_ui.pk).exists())
        self.assertTrue(BatchRecord.objects.filter(pk=FIXTURE_ATTEMPT).exists())

    def test_keeps_api_keys(self):
        api_key, _ = ApiKey.objects.create_key(name="GCI")
        call_command("load_css_sample_data", verbosity=0)
        self.assertTrue(ApiKey.objects.filter(pk=api_key.pk).exists())
