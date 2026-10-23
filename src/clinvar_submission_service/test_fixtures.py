from django.contrib.auth.models import User
from django.test import TestCase

from auth_.models import UserProfile
from clinvar_submission_service.content import Content, record_fields
from clinvar_submission_service.models import Batch
from clinvar_submission_service.services import build_payload
from common.models import make_slug

FORWARDED_STATUSES = {
    Batch.Status.SUBMITTED_TO_CLINVAR,
    Batch.Status.PROCESSING_AT_CLINVAR,
    Batch.Status.PROCESSED_BY_CLINVAR,
    Batch.Status.ERROR_AT_CLINVAR,
}


class BatchFixtureTest(TestCase):
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
                    for name, value in expected.items():
                        self.assertEqual(getattr(record, name), value, name)
                    self.assertEqual(record.affiliation_id, batch.affiliation_id)

    def test_every_submissions_page_renders(self):
        user = User.objects.create_user(username="staff@example.com")
        UserProfile.objects.create(user=user, has_css_permissions=True)
        self.client.force_login(user)
        for batch in Batch.objects.all():
            with self.subTest(batch.slug):
                response = self.client.get(batch.get_absolute_url())
                self.assertEqual(response.status_code, 200)
