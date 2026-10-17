from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from auth_.models import UserProfile
from clinvar_submission_service.clients import ClinVarError
from clinvar_submission_service.fakes import FakeClinVarClient
from clinvar_submission_service.models import ApiKey, Submission
from clinvar_submission_service.views import PAGE_SIZE

REPORT = {
    "totalCount": 2,
    "totalErrors": 1,
    "totalSuccess": 1,
    "submissions": [
        {
            "identifiers": {"localID": "var-1", "clinvarAccession": "SCV000000001"},
            "processingStatus": "Success",
        },
        {"identifiers": {"localID": "var-2"}, "processingStatus": "Error"},
    ],
}


def _make_user(username: str, *, css: bool = False) -> User:
    """Returns a user whose profile has the given CSS permission."""
    user = User.objects.create_user(username=username, email=username)
    UserProfile.objects.create(user=user, has_css_permissions=css)
    return user


class CssViewTestCase(TestCase):
    def setUp(self):
        self.user = _make_user("staff@example.com", css=True)
        self.client.force_login(self.user)
        self.api_key, _ = ApiKey.objects.create_key(name="GCI")

    def _make(self, **fields: object) -> Submission:
        return Submission.objects.create(api_key=self.api_key, payload={}, **fields)


class PermissionTest(CssViewTestCase):
    def test_every_page_needs_css_permissions(self):
        submission = self._make(status=Submission.Status.SEND_FAILED)
        pages = [
            ("get", reverse("css:index")),
            ("get", submission.get_absolute_url()),
            ("post", reverse("css:resend", kwargs={"slug": submission.slug})),
        ]
        self.client.force_login(_make_user("other@example.com"))
        for method, url in pages:
            with self.subTest(url=url):
                self.assertEqual(getattr(self.client, method)(url).status_code, 403)


class ListViewTest(CssViewTestCase):
    def test_lists_submissions_newest_first(self):
        older = self._make(clinvar_submission_id="SUB000001")
        newer = self._make(clinvar_submission_id="SUB000002")
        response = self.client.get(reverse("css:index"))
        self.assertTemplateUsed(response, "clinvar_submission_service/list.html")
        self.assertEqual(list(response.context["page"]), [newer, older])
        self.assertContains(response, newer.get_absolute_url())
        self.assertContains(response, "GCI")
        self.assertContains(response, "SUB000002")

    def test_searches_by_slug_or_clinvar_id(self):
        match = self._make(clinvar_submission_id="SUB123456")
        other = self._make(clinvar_submission_id="SUB999999")
        for query in ("SUB123456", "sub1234", match.slug):
            with self.subTest(query=query):
                response = self.client.get(reverse("css:index"), {"q": query})
                self.assertEqual(list(response.context["page"]), [match])
        self.assertNotContains(
            self.client.get(reverse("css:index"), {"q": "SUB123456"}), other.slug
        )

    def test_is_paginated(self):
        for _ in range(PAGE_SIZE + 1):
            self._make()
        response = self.client.get(reverse("css:index"), {"page": 2})
        self.assertEqual(len(response.context["page"]), 1)

    def test_says_so_when_there_are_none(self):
        response = self.client.get(reverse("css:index"))
        self.assertContains(response, "No submissions yet.")

    def test_has_the_header_with_the_list_tab_active(self):
        response = self.client.get(reverse("css:index"))
        self.assertContains(response, "ClinVar Submission Service")
        self.assertContains(
            response,
            f'<a href="{reverse("css:index")}" aria-current="page">',
        )


class StatusTagTest(CssViewTestCase):
    def test_each_status_has_its_color(self):
        colors = {
            Submission.Status.RECEIVED: 'class="tag is-light"',
            Submission.Status.SUBMITTED: 'class="tag is-light"',
            Submission.Status.PROCESSING: 'class="tag is-light"',
            Submission.Status.SEND_FAILED: 'class="tag is-danger is-light"',
            Submission.Status.ERROR: 'class="tag is-danger is-light"',
            Submission.Status.PROCESSED: 'class="tag is-success is-light"',
        }
        for status, css_class in colors.items():
            with self.subTest(status=status):
                submission = self._make(status=status)
                response = self.client.get(submission.get_absolute_url())
                self.assertContains(response, css_class)


class DetailViewTest(CssViewTestCase):
    def test_shows_the_submission(self):
        submission = self._make(
            status=Submission.Status.ERROR,
            clinvar_submission_id="SUB000009",
            summary_report=REPORT,
        )
        response = self.client.get(submission.get_absolute_url())
        self.assertTemplateUsed(response, "clinvar_submission_service/detail.html")
        self.assertContains(response, "SUB000009")
        self.assertContains(response, "GCI")
        self.assertContains(response, "var-1")
        self.assertContains(response, "SCV000000001")
        self.assertContains(response, f"Submission {submission.slug}")

    def test_never_shows_the_raw_error(self):
        submission = self._make(
            status=Submission.Status.SEND_FAILED,
            error_message="ClinVar returned 401: No valid API key provided",
        )
        response = self.client.get(submission.get_absolute_url())
        self.assertNotContains(response, "401")
        self.assertContains(response, "ClinVar never got this submission.")

    def test_unknown_slug_is_404(self):
        response = self.client.get(reverse("css:detail", kwargs={"slug": "Snope"}))
        self.assertEqual(response.status_code, 404)

    def test_resend_button_is_only_for_send_failed(self):
        for status in Submission.Status:
            with self.subTest(status=status):
                submission = self._make(status=status)
                response = self.client.get(submission.get_absolute_url())
                resend_url = reverse("css:resend", kwargs={"slug": submission.slug})
                if status == Submission.Status.SEND_FAILED:
                    self.assertContains(response, resend_url)
                else:
                    self.assertNotContains(response, resend_url)


class ResendViewTest(CssViewTestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeClinVarClient()
        patcher = mock.patch(
            "clinvar_submission_service.services.ClinVarClient.from_settings",
            return_value=self.fake,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def resend(self, submission: Submission):
        return self.client.post(
            reverse("css:resend", kwargs={"slug": submission.slug}), follow=True
        )

    def test_a_successful_resend_sends_it_to_clinvar(self):
        submission = self._make(status=Submission.Status.SEND_FAILED)
        response = self.resend(submission)
        self.assertRedirects(response, submission.get_absolute_url())
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.SUBMITTED)
        self.assertEqual(submission.clinvar_submission_id, "SUB000001")
        self.assertEqual(submission.history.first().history_user, self.user)  # type: ignore

    def test_a_failed_resend_stays_send_failed_with_the_new_error(self):
        self.fake.submit_error = ClinVarError("ClinVar returned 503", retryable=True)
        submission = self._make(
            status=Submission.Status.SEND_FAILED, error_message="old error"
        )
        response = self.resend(submission)
        submission.refresh_from_db()
        self.assertEqual(submission.status, Submission.Status.SEND_FAILED)
        self.assertEqual(submission.error_message, "ClinVar returned 503")
        self.assertContains(response, "ClinVar still didn&#x27;t get the submission.")
        self.assertNotContains(response, "503")

    def test_only_send_failed_submissions_can_be_resent(self):
        submission = self._make(
            status=Submission.Status.SUBMITTED, clinvar_submission_id="SUB000005"
        )
        response = self.resend(submission)
        self.assertContains(
            response, "Only a submission ClinVar never got can be resent."
        )
        submission.refresh_from_db()
        self.assertEqual(submission.clinvar_submission_id, "SUB000005")
        self.assertEqual(self.fake.submitted, [])

    def test_resend_needs_a_post(self):
        submission = self._make(status=Submission.Status.SEND_FAILED)
        response = self.client.get(
            reverse("css:resend", kwargs={"slug": submission.slug})
        )
        self.assertEqual(response.status_code, 405)
