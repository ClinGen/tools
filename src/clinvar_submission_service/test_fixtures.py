from django.contrib.auth.models import User
from django.test import TestCase

from auth_.models import UserProfile
from clinvar_submission_service.content import Content, record_fields
from clinvar_submission_service.models import Record, Submission
from common.models import make_slug

FORWARDED_STATUSES = {
    Submission.Status.SUBMITTED,
    Submission.Status.PROCESSING,
    Submission.Status.PROCESSED,
    Submission.Status.ERROR,
}


class SubmissionFixtureTest(TestCase):
    fixtures = ["test_submissions.json"]

    def test_has_a_submission_in_every_status(self):
        statuses = set(Submission.objects.values_list("status", flat=True))
        self.assertEqual(statuses, set(Submission.Status.values))

    def test_slugs_come_from_random_looking_uuids(self):
        for submission in Submission.objects.all():
            with self.subTest(submission.slug):
                self.assertEqual(submission.slug, make_slug("S", submission.pk))
                # Hand-numbered UUIDs would give slugs like S00000006.
                self.assertNotRegex(submission.slug, r"^S0000")

    def test_only_forwarded_submissions_have_a_clinvar_id(self):
        for submission in Submission.objects.all():
            with self.subTest(submission.status):
                forwarded = submission.status in FORWARDED_STATUSES
                self.assertEqual(bool(submission.clinvar_submission_id), forwarded)

    def test_only_finished_submissions_have_a_summary_report(self):
        for submission in Submission.objects.all():
            with self.subTest(submission.status):
                finished = submission.status in {
                    Submission.Status.PROCESSED,
                    Submission.Status.ERROR,
                }
                self.assertEqual(submission.summary_report is not None, finished)

    def test_each_submissions_records_match_its_payload(self):
        fields = [field.name for field in Record._meta.fields]  # ruff: ignore[private-member-access] (Django's documented API.)
        fields = [name for name in fields if name not in ("id", "submission")]
        for submission in Submission.objects.all():
            with self.subTest(submission.slug):
                content = Content.model_validate(submission.payload)
                records = submission.records.order_by("local_id").values(*fields)  # type: ignore
                expected = sorted(record_fields(content), key=lambda r: r["local_id"])
                self.assertEqual(list(records), expected)

    def test_every_submissions_page_renders(self):
        user = User.objects.create_user(username="staff@example.com")
        UserProfile.objects.create(user=user, has_css_permissions=True)
        self.client.force_login(user)
        for submission in Submission.objects.all():
            with self.subTest(submission.slug):
                response = self.client.get(submission.get_absolute_url())
                self.assertEqual(response.status_code, 200)
