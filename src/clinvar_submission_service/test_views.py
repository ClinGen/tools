from typing import TYPE_CHECKING
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from auth_.models import UserProfile
from clinvar_submission_service.clients import ClinVarError
from clinvar_submission_service.content import Content, record_fields
from clinvar_submission_service.fakes import (
    FakeClinVarClient,
    make_content,
    make_record,
)
from clinvar_submission_service.models import ApiKey, Record, Submission
from clinvar_submission_service.views import PAGE_SIZE

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse as Response

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


def _listed(response: "Response") -> list[Submission]:
    """Returns the submissions on the list page's current page, in order."""
    return [row.record for row in response.context["table"].paginated_rows]


class CssViewTestCase(TestCase):
    def setUp(self):
        self.user = _make_user("staff@example.com", css=True)
        self.client.force_login(self.user)
        self.api_key, _ = ApiKey.objects.create_key(name="GCI")

    def _make(self, *records: dict, **fields: object) -> Submission:
        """Returns a submission from the Hearing Loss VCEP with the given records."""
        payload = make_content(*records) if records else {}
        defaults = {"affiliation_id": 10007, "affiliation_name": "Hearing Loss VCEP"}
        submission = Submission.objects.create(
            api_key=self.api_key, payload=payload, **(defaults | fields)
        )
        if records:
            for row in record_fields(Content.model_validate(payload)):
                Record.objects.create(submission=submission, **row)
        return submission


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
        self.assertEqual(_listed(response), [newer, older])
        self.assertContains(response, newer.get_absolute_url())
        self.assertContains(response, "GCI")
        self.assertContains(response, "SUB000002")

    def test_searches_by_slug_or_clinvar_id(self):
        match = self._make(clinvar_submission_id="SUB123456")
        other = self._make(clinvar_submission_id="SUB999999")
        for query in ("SUB123456", "sub1234", match.slug):
            with self.subTest(query=query):
                response = self.client.get(reverse("css:index"), {"q": query})
                self.assertEqual(_listed(response), [match])
        self.assertNotContains(
            self.client.get(reverse("css:index"), {"q": "SUB123456"}), other.slug
        )

    def test_is_paginated(self):
        for _ in range(PAGE_SIZE + 1):
            self._make()
        response = self.client.get(reverse("css:index"), {"page": 2})
        self.assertEqual(len(_listed(response)), 1)

    def test_shows_each_submissions_affiliation_and_variants(self):
        self._make(
            make_record("var-1"),
            make_record(
                "var-2",
                variantSet={
                    "variant": [
                        {
                            "hgvs": "NC_000014.9:g.23431584C>T",
                            "gene": [{"symbol": "MYH7"}],
                        }
                    ]
                },
            ),
        )
        response = self.client.get(reverse("css:index"))
        self.assertContains(response, "Hearing Loss VCEP")
        self.assertContains(response, "BRCA1")
        self.assertContains(response, "MYH7")

    def test_filters_to_submissions_clinvar_never_got_or_got(self):
        received = self._make(status=Submission.Status.RECEIVED)
        send_failed = self._make(status=Submission.Status.SEND_FAILED)
        submitted = self._make(status=Submission.Status.SUBMITTED)
        processing = self._make(status=Submission.Status.PROCESSING)
        processed = self._make(status=Submission.Status.PROCESSED)
        error = self._make(status=Submission.Status.ERROR)
        cases = {
            "": {received, send_failed, submitted, processing, processed, error},
            "not_sent": {received, send_failed},
            "sent": {submitted, processing, processed, error},
            "unknown": {received, send_failed, submitted, processing, processed, error},
        }
        for sent, expected in cases.items():
            with self.subTest(sent=sent):
                response = self.client.get(reverse("css:index"), {"sent": sent})
                self.assertEqual(set(_listed(response)), expected)

    def test_the_active_filter_is_marked(self):
        response = self.client.get(reverse("css:index"), {"sent": "not_sent"})
        self.assertContains(
            response,
            '<a href="?sent=not_sent" aria-current="page">Not Sent to ClinVar</a>',
            html=True,
        )

    def test_searches_by_affiliation_gene_or_hgvs(self):
        match = self._make(make_record("var-1"), affiliation_name="TP53 VCEP")
        self._make(
            make_record(
                "var-2",
                variantSet={
                    "variant": [
                        {
                            "hgvs": "NC_000014.9:g.23431584C>T",
                            "gene": [{"symbol": "MYH7"}],
                        }
                    ]
                },
            ),
        )
        for query in ("tp53 vcep", "BRCA1", "43045712T>C"):
            with self.subTest(query=query):
                response = self.client.get(reverse("css:index"), {"q": query})
                self.assertEqual(_listed(response), [match])

    def test_search_keeps_the_filter(self):
        self._make(status=Submission.Status.SUBMITTED, clinvar_submission_id="SUB1")
        response = self.client.get(
            reverse("css:index"), {"q": "SUB1", "sent": "not_sent"}
        )
        self.assertEqual(_listed(response), [])
        self.assertContains(response, 'name="sent" value="not_sent"')

    def test_sorts_by_a_column(self):
        first = self._make(clinvar_submission_id="SUB000001")
        second = self._make(clinvar_submission_id="SUB000002")
        for sort, expected in (
            ("clinvar_submission_id", [first, second]),
            ("-clinvar_submission_id", [second, first]),
        ):
            with self.subTest(sort=sort):
                response = self.client.get(reverse("css:index"), {"sort": sort})
                self.assertEqual(_listed(response), expected)

    def test_page_links_keep_the_search_and_filters(self):
        for _ in range(PAGE_SIZE + 1):
            self._make(status=Submission.Status.RECEIVED)
        params = {"q": "Hearing", "sent": "not_sent", "affiliation": "10007"}
        response = self.client.get(reverse("css:index"), params)
        self.assertContains(
            response, "?q=Hearing&amp;sent=not_sent&amp;affiliation=10007&amp;page=2"
        )

    def test_an_htmx_request_gets_only_the_results(self):
        self._make()
        response = self.client.get(reverse("css:index"), HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(
            response, "clinvar_submission_service/partials/results.html"
        )
        self.assertTemplateNotUsed(response, "clinvar_submission_service/list.html")
        self.assertContains(response, "1 submission")

    def test_the_search_box_sends_the_filters_as_you_type(self):
        response = self.client.get(reverse("css:index"), {"affiliation": "10007"})
        self.assertContains(response, 'hx-include="closest form"')
        self.assertContains(response, 'name="affiliation" value="10007"')

    def test_says_when_the_css_received_each_submission(self):
        self._make()
        self.assertContains(self.client.get(reverse("css:index")), "Received by CSS")

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
            make_record("var-1"),
            make_record("var-2"),
            status=Submission.Status.ERROR,
            clinvar_submission_id="SUB000009",
            summary_report=REPORT,
        )
        response = self.client.get(submission.get_absolute_url())
        self.assertTemplateUsed(response, "clinvar_submission_service/detail.html")
        self.assertContains(response, "SUB000009")
        self.assertContains(response, "GCI")
        self.assertContains(response, "Hearing Loss VCEP")
        self.assertContains(response, f"Submission {submission.slug}")

    def test_the_submission_tab_comes_between_submissions_and_affiliations(self):
        submission = self._make()
        html = self.client.get(submission.get_absolute_url()).content.decode()
        tabs = ["Submissions", f"Submission {submission.slug}", "Affiliations"]
        positions = [html.index(f"<span>{tab}</span>") for tab in tabs]
        self.assertEqual(positions, sorted(positions))

    def test_shows_each_records_classification_and_clinvar_result(self):
        submission = self._make(
            make_record("var-1"),
            make_record("var-2"),
            status=Submission.Status.ERROR,
            summary_report=REPORT,
        )
        response = self.client.get(submission.get_absolute_url())
        rows = response.context["rows"]
        self.assertEqual([row.record.local_id for row in rows], ["var-1", "var-2"])
        self.assertEqual(rows[0].scv, "SCV000000001")
        self.assertTrue(rows[0].accepted)
        self.assertFalse(rows[1].accepted)
        for text in (
            "BRCA1",
            "NC_000017.11:g.43045712T&gt;C",
            "MONDO:0011450",
            "Likely Pathogenic",
            "Autosomal Dominant",
            "2026-10-01",
            "SCV000000001",
            "Not Accepted",
        ):
            with self.subTest(text=text):
                self.assertContains(response, text)

    def test_records_have_no_result_before_clinvar_reports(self):
        submission = self._make(
            make_record("var-1"), status=Submission.Status.SUBMITTED
        )
        response = self.client.get(submission.get_absolute_url())
        (row,) = response.context["rows"]
        self.assertIsNone(row.accepted)
        self.assertContains(response, "Waiting for ClinVar")

    def test_records_clinvar_never_got_say_so(self):
        submission = self._make(
            make_record("var-1"), status=Submission.Status.SEND_FAILED
        )
        response = self.client.get(submission.get_absolute_url())
        self.assertContains(response, "Not Sent")
        self.assertNotContains(response, "Waiting for ClinVar")

    def test_an_update_names_the_record_it_updates(self):
        submission = self._make(
            make_record("var-1", recordStatus="update", clinvarAccession="SCV000575021")
        )
        response = self.client.get(submission.get_absolute_url())
        self.assertContains(response, "Update to SCV000575021")

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


class AffiliationTestCase(TestCase):
    fixtures = ["test_submissions.json"]

    def setUp(self):
        self.client.force_login(_make_user("staff@example.com", css=True))


class AffiliationFilterTest(AffiliationTestCase):
    def test_filters_the_list_to_one_affiliation(self):
        response = self.client.get(reverse("css:index"), {"affiliation": "10901"})
        names = {s.affiliation_name for s in _listed(response)}
        self.assertEqual(names, {"Cardiomyopathy VCEP"})
        self.assertEqual(len(_listed(response)), 3)
        self.assertContains(response, "Showing submissions from Cardiomyopathy VCEP.")

    def test_combines_with_the_sent_filter(self):
        response = self.client.get(
            reverse("css:index"), {"affiliation": "10901", "sent": "not_sent"}
        )
        self.assertEqual(
            [s.status for s in _listed(response)], [Submission.Status.RECEIVED]
        )
        self.assertContains(response, 'href="?affiliation=10901&amp;sent=sent"')

    def test_an_unknown_affiliation_shows_nothing(self):
        for value in ("99999", "not-a-number"):
            with self.subTest(value=value):
                response = self.client.get(reverse("css:index"), {"affiliation": value})
                self.assertEqual(_listed(response), [])


class AffiliationsViewTest(AffiliationTestCase):
    def test_needs_css_permissions(self):
        self.client.force_login(_make_user("other@example.com"))
        response = self.client.get(reverse("css:affiliations"))
        self.assertEqual(response.status_code, 403)

    def test_counts_each_affiliations_submissions(self):
        response = self.client.get(reverse("css:affiliations"))
        self.assertTemplateUsed(
            response, "clinvar_submission_service/affiliations.html"
        )
        counts = {
            row["name"]: (
                row["not_sent"],
                row["waiting"],
                row["accepted"],
                row["errors"],
                row["total"],
            )
            for row in response.context["affiliations"]
        }
        self.assertEqual(
            counts,
            {
                "CDH1 VCEP": (0, 0, 0, 1, 1),
                "Cardiomyopathy VCEP": (1, 1, 1, 0, 3),
                "Malignant Hyperthermia Susceptibility VCEP": (0, 1, 0, 0, 1),
                "Phenylketonuria VCEP": (0, 0, 1, 0, 1),
                "TP53 VCEP": (1, 0, 0, 1, 2),
            },
        )

    def test_lists_affiliations_by_name_with_links_to_their_submissions(self):
        response = self.client.get(reverse("css:affiliations"))
        names = [row["name"] for row in response.context["affiliations"]]
        self.assertEqual(names, sorted(names))
        self.assertContains(response, f"{reverse('css:index')}?affiliation=10901")

    def test_the_header_has_an_affiliations_tab(self):
        response = self.client.get(reverse("css:affiliations"))
        self.assertContains(
            response, f'<a href="{reverse("css:affiliations")}" aria-current="page">'
        )
