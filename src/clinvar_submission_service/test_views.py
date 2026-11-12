import re
from typing import TYPE_CHECKING
from unittest import mock

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils.html import escape

from auth_.models import UserProfile
from clinvar_submission_service.clients import ClinVarError
from clinvar_submission_service.content import Content, record_fields
from clinvar_submission_service.fakes import (
    FakeClinVarClient,
    make_content,
    make_record,
)
from clinvar_submission_service.models import (
    AffiliationSettings,
    ApiKey,
    Batch,
    BatchRecord,
    Record,
)
from clinvar_submission_service.services import withdraw_record
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


def _listed(response: "Response") -> list:
    """Returns the batches or records on a list page's current page, in order."""
    return [row.record for row in response.context["table"].paginated_rows]


class CssViewTestCase(TestCase):
    def setUp(self):
        self.user = _make_user("staff@example.com", css=True)
        self.client.force_login(self.user)
        self.api_key, _ = ApiKey.objects.create_key(name="GCI")

    def _make(self, *records: dict, **fields: object) -> Batch:
        """Returns a batch from the Hearing Loss VCEP with the given records."""
        payload = make_content(*records) if records else {}
        defaults = {
            "made_by": self.user,
            "affiliation_id": 10007,
            "affiliation_name": "Hearing Loss VCEP",
        }
        batch = Batch.objects.create(**(defaults | fields))
        if records:
            content = Content.model_validate(payload)
            for position, row in enumerate(record_fields(content)):
                record = Record.objects.create(**row)
                BatchRecord.objects.create(
                    batch=batch, record=record, position=position
                )
        return batch


class PermissionTest(CssViewTestCase):
    def test_every_page_needs_css_permissions(self):
        batch = self._make(make_record(), status=Batch.Status.SEND_TO_CLINVAR_FAILED)
        record = batch.records.get()
        pages = [
            ("get", reverse("css:batches")),
            ("get", batch.get_absolute_url()),
            ("post", reverse("css:resend", kwargs={"slug": batch.slug})),
            ("post", reverse("css:withdraw", kwargs={"slug": record.slug})),
            ("get", _settings_url(10007)),
            ("post", _settings_url(10007)),
            ("get", reverse("css:records")),
            ("get", _new_batch_url(10007)),
            ("post", _new_batch_url(10007)),
            ("get", record.get_absolute_url()),
        ]
        self.client.force_login(_make_user("other@example.com"))
        for method, url in pages:
            with self.subTest(url=url):
                self.assertEqual(getattr(self.client, method)(url).status_code, 403)


class MadeByTest(CssViewTestCase):
    def test_a_batch_with_no_recorded_maker_shows_nothing(self):
        batch = self._make(made_by=None)
        self.assertEqual(self.client.get(reverse("css:batches")).status_code, 200)
        response = self.client.get(batch.get_absolute_url())
        self.assertContains(response, "<td>Made By</td><td></td>")


class ListViewTest(CssViewTestCase):
    def test_lists_submissions_newest_first(self):
        older = self._make(clinvar_submission_id="SUB000001")
        newer = self._make(clinvar_submission_id="SUB000002")
        response = self.client.get(reverse("css:batches"))
        self.assertTemplateUsed(response, "clinvar_submission_service/list.html")
        self.assertEqual(_listed(response), [newer, older])
        self.assertContains(response, newer.get_absolute_url())
        self.assertContains(response, "Made By")
        self.assertContains(response, "staff@example.com")
        self.assertContains(response, "SUB000002")

    def test_searches_by_slug_or_clinvar_id(self):
        match = self._make(clinvar_submission_id="SUB123456")
        other = self._make(clinvar_submission_id="SUB999999")
        for query in ("SUB123456", "sub1234", match.slug):
            with self.subTest(query=query):
                response = self.client.get(reverse("css:batches"), {"q": query})
                self.assertEqual(_listed(response), [match])
        self.assertNotContains(
            self.client.get(reverse("css:batches"), {"q": "SUB123456"}), other.slug
        )

    def test_is_paginated(self):
        for _ in range(PAGE_SIZE + 1):
            self._make()
        response = self.client.get(reverse("css:batches"), {"page": 2})
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
        response = self.client.get(reverse("css:batches"))
        self.assertContains(response, "Hearing Loss VCEP")
        self.assertContains(response, "BRCA1")
        self.assertContains(response, "MYH7")

    def test_filters_to_each_status(self):
        by_status = {
            status: self._make(status=status) for status in Batch.Status.values
        }
        for status, batch in by_status.items():
            with self.subTest(status=status):
                response = self.client.get(reverse("css:batches"), {"status": status})
                self.assertEqual(_listed(response), [batch])
        for status in ("", "received", "unknown"):
            with self.subTest(status=status):
                response = self.client.get(reverse("css:batches"), {"status": status})
                self.assertEqual(set(_listed(response)), set(by_status.values()))

    def test_has_a_pill_for_all_and_each_status(self):
        response = self.client.get(reverse("css:batches"))
        self.assertContains(
            response, '<a href="?" aria-current="page">All</a>', html=True
        )
        for value, label in Batch.Status.choices:
            with self.subTest(status=value):
                self.assertContains(
                    response, f'<a href="?status={value}">{label}</a>', html=True
                )

    def test_the_active_filter_is_marked(self):
        response = self.client.get(
            reverse("css:batches"), {"status": "submitted_to_clinvar"}
        )
        self.assertContains(
            response,
            '<a href="?status=submitted_to_clinvar" aria-current="page">Submitted</a>',
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
                response = self.client.get(reverse("css:batches"), {"q": query})
                self.assertEqual(_listed(response), [match])

    def test_search_keeps_the_filter(self):
        self._make(
            status=Batch.Status.SUBMITTED_TO_CLINVAR, clinvar_submission_id="SUB1"
        )
        response = self.client.get(
            reverse("css:batches"), {"q": "SUB1", "status": "not_sent_to_clinvar"}
        )
        self.assertEqual(_listed(response), [])
        self.assertContains(response, 'name="status" value="not_sent_to_clinvar"')

    def test_sorts_by_a_column(self):
        first = self._make(clinvar_submission_id="SUB000001")
        second = self._make(clinvar_submission_id="SUB000002")
        for sort, expected in (
            ("clinvar_submission_id", [first, second]),
            ("-clinvar_submission_id", [second, first]),
        ):
            with self.subTest(sort=sort):
                response = self.client.get(reverse("css:batches"), {"sort": sort})
                self.assertEqual(_listed(response), expected)

    def test_page_links_keep_the_search_and_filters(self):
        for _ in range(PAGE_SIZE + 1):
            self._make(status=Batch.Status.NOT_SENT_TO_CLINVAR)
        params = {
            "q": "Hearing",
            "status": "not_sent_to_clinvar",
            "affiliation": "10007",
        }
        response = self.client.get(reverse("css:batches"), params)
        self.assertContains(
            response,
            "?q=Hearing&amp;status=not_sent_to_clinvar&amp;affiliation=10007&amp;page=2",
        )

    def test_an_htmx_request_gets_only_the_results(self):
        self._make()
        response = self.client.get(reverse("css:batches"), HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(
            response, "clinvar_submission_service/partials/results.html"
        )
        self.assertTemplateNotUsed(response, "clinvar_submission_service/list.html")
        self.assertContains(response, "1 batch")

    def test_the_search_box_sends_the_filters_as_you_type(self):
        self._make()
        response = self.client.get(reverse("css:batches"), {"affiliation": "10007"})
        self.assertContains(response, 'hx-include="closest form"')
        self.assertContains(
            response, '<option value="10007" selected>Hearing Loss VCEP</option>'
        )

    def test_says_when_the_css_received_each_batch(self):
        self._make()
        self.assertContains(self.client.get(reverse("css:batches")), "Received by CSS")

    def test_says_so_when_there_are_none(self):
        response = self.client.get(reverse("css:batches"))
        self.assertContains(response, "No batches yet.")


class StatusTagTest(CssViewTestCase):
    def test_each_status_has_clinvars_wording_and_a_tooltip(self):
        labels = {
            Batch.Status.NOT_SENT_TO_CLINVAR: "Not Sent",
            Batch.Status.SEND_TO_CLINVAR_FAILED: "Send Failed",
            Batch.Status.SUBMITTED_TO_CLINVAR: "Submitted",
            Batch.Status.PROCESSING_AT_CLINVAR: "Processing",
            Batch.Status.PROCESSED_BY_CLINVAR: "Processed",
            Batch.Status.ERROR_AT_CLINVAR: "Error",
        }
        for status, label in labels.items():
            with self.subTest(status=status):
                batch = self._make(status=status)
                html = self.client.get(batch.get_absolute_url()).content.decode()
                help_text = escape(Batch.STATUS_HELP[status])
                # The tooltip is on the tag itself, not on an icon beside it.
                self.assertRegex(
                    html,
                    rf'<span class="tag[^"]*" data-tippy-content="{help_text}" '
                    rf'tabindex="0"[^>]*>{label}<span class="is-sr-only">',
                )
                self.assertNotIn("bi-info-circle", html)

    def test_an_errors_tooltip_says_whether_some_or_all_records_failed(self):
        for code, text in (
            (1, "Some records in the batch succeeded, and others failed."),
            (2, "All records in the batch failed."),
            (None, "One or more records in the batch failed."),
        ):
            with self.subTest(code=code):
                batch = self._make(
                    status=Batch.Status.ERROR_AT_CLINVAR, clinvar_error_code=code
                )
                self.assertEqual(batch.status_help, text)
                response = self.client.get(batch.get_absolute_url())
                self.assertContains(response, f'data-tippy-content="{escape(text)}"')

    def test_the_list_shows_each_status_tooltip(self):
        self._make(status=Batch.Status.SUBMITTED_TO_CLINVAR)
        help_text = Batch.STATUS_HELP[Batch.Status.SUBMITTED_TO_CLINVAR]
        response = self.client.get(reverse("css:batches"))
        self.assertContains(response, f'data-tippy-content="{escape(help_text)}"')

    def test_each_tag_in_the_list_links_to_its_status(self):
        for status in Batch.Status.values:
            self._make(status=status)
        html = self.client.get(reverse("css:batches")).content.decode()
        for status in Batch.Status.values:
            with self.subTest(status=status):
                help_text = escape(Batch.STATUS_HELP[status])
                self.assertRegex(
                    html,
                    rf'<a href="\?status={status}" class="tag[^"]*" '
                    rf'data-tippy-content="{help_text}">',
                )

    def test_a_tags_link_keeps_the_affiliation(self):
        self._make(status=Batch.Status.PROCESSED_BY_CLINVAR)
        response = self.client.get(reverse("css:batches"), {"affiliation": "10007"})
        self.assertContains(
            response,
            '<a href="?affiliation=10007&amp;status=processed_by_clinvar" class="tag',
        )

    def test_the_detail_pages_tag_isnt_a_link(self):
        batch = self._make(status=Batch.Status.PROCESSED_BY_CLINVAR)
        response = self.client.get(batch.get_absolute_url())
        self.assertContains(response, '<span class="tag is-success is-light"')
        self.assertNotRegex(response.content.decode(), r'<a [^>]*class="tag')

    def test_no_page_uses_the_old_wording(self):
        for status in Batch.Status.values:
            self._make(make_record("var-1"), status=status)
        pages = [reverse("css:batches"), reverse("css:affiliations")]
        pages += [s.get_absolute_url() for s in Batch.objects.all()]
        old = ["Not Sent Yet", "ClinVar Is Checking", "Has Errors", "Accepted<"]
        old += ["Not Accepted", "Waiting for ClinVar", ">Sent<", ">Sent to ClinVar<"]
        for url in pages:
            html = self.client.get(url).content.decode()
            for text in old:
                with self.subTest(url=url, text=text):
                    self.assertNotIn(text, html)

    def test_each_status_has_its_color(self):
        colors = {
            Batch.Status.NOT_SENT_TO_CLINVAR: 'class="tag is-light"',
            Batch.Status.SUBMITTED_TO_CLINVAR: 'class="tag is-light"',
            Batch.Status.PROCESSING_AT_CLINVAR: 'class="tag is-light"',
            Batch.Status.SEND_TO_CLINVAR_FAILED: 'class="tag is-danger is-light"',
            Batch.Status.ERROR_AT_CLINVAR: 'class="tag is-danger is-light"',
            Batch.Status.PROCESSED_BY_CLINVAR: 'class="tag is-success is-light"',
        }
        for status, css_class in colors.items():
            with self.subTest(status=status):
                batch = self._make(status=status)
                response = self.client.get(batch.get_absolute_url())
                self.assertContains(response, css_class)


class DetailViewTest(CssViewTestCase):
    def test_shows_the_batch(self):
        batch = self._make(
            make_record("var-1"),
            make_record("var-2"),
            status=Batch.Status.ERROR_AT_CLINVAR,
            clinvar_submission_id="SUB000009",
            summary_report=REPORT,
        )
        response = self.client.get(batch.get_absolute_url())
        self.assertTemplateUsed(response, "clinvar_submission_service/detail.html")
        self.assertContains(response, "SUB000009")
        self.assertContains(response, "<td>Made By</td><td>staff@example.com</td>")
        self.assertContains(response, "Hearing Loss VCEP")
        self.assertContains(response, f"{batch.slug} Details")

    def test_shows_each_records_classification_and_clinvar_result(self):
        batch = self._make(
            make_record("var-1"),
            make_record("var-2"),
            status=Batch.Status.ERROR_AT_CLINVAR,
            summary_report=REPORT,
        )
        response = self.client.get(batch.get_absolute_url())
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
            (
                '<span class="tag is-success is-light" data-tippy-content="ClinVar '
                'accepted this record." tabindex="0"'
            ),
            (
                '<span class="tag is-danger is-light" data-tippy-content="ClinVar '
                "didn't accept this record."
            ),
        ):
            with self.subTest(text=text):
                self.assertContains(response, text)

    def test_records_have_no_result_before_clinvar_reports(self):
        batch = self._make(
            make_record("var-1"), status=Batch.Status.SUBMITTED_TO_CLINVAR
        )
        response = self.client.get(batch.get_absolute_url())
        (row,) = response.context["rows"]
        self.assertIsNone(row.accepted)
        self.assertContains(response, "No Result Yet")

    def test_records_clinvar_never_got_say_so(self):
        batch = self._make(
            make_record("var-1"), status=Batch.Status.SEND_TO_CLINVAR_FAILED
        )
        response = self.client.get(batch.get_absolute_url())
        self.assertContains(
            response,
            '">Not Sent<span class="is-sr-only">',
        )
        self.assertNotContains(response, "No Result Yet")

    def test_an_update_names_the_record_it_updates(self):
        batch = self._make(
            make_record("var-1", recordStatus="update", clinvarAccession="SCV000575021")
        )
        response = self.client.get(batch.get_absolute_url())
        self.assertContains(response, "Update to SCV000575021")

    def test_never_shows_the_raw_error(self):
        batch = self._make(
            status=Batch.Status.SEND_TO_CLINVAR_FAILED,
            error_message="ClinVar returned 401: No valid API key provided",
        )
        response = self.client.get(batch.get_absolute_url())
        # A random ID on the page can hold "401", so check for the error's words.
        self.assertNotContains(response, "No valid API key provided")
        self.assertContains(response, "ClinVar never got this batch.")

    def test_unknown_slug_is_404(self):
        response = self.client.get(reverse("css:detail", kwargs={"slug": "Snope"}))
        self.assertEqual(response.status_code, 404)

    def test_resend_button_is_only_for_send_failed(self):
        for status in Batch.Status:
            with self.subTest(status=status):
                batch = self._make(status=status)
                response = self.client.get(batch.get_absolute_url())
                resend_url = reverse("css:resend", kwargs={"slug": batch.slug})
                if status == Batch.Status.SEND_TO_CLINVAR_FAILED:
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

    def resend(self, batch: Batch):
        return self.client.post(
            reverse("css:resend", kwargs={"slug": batch.slug}), follow=True
        )

    def test_a_successful_resend_sends_it_to_clinvar(self):
        batch = self._make(status=Batch.Status.SEND_TO_CLINVAR_FAILED)
        response = self.resend(batch)
        self.assertRedirects(response, batch.get_absolute_url())
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.SUBMITTED_TO_CLINVAR)
        self.assertEqual(batch.clinvar_submission_id, "SUB000001")
        self.assertEqual(batch.history.first().history_user, self.user)  # type: ignore

    def test_a_failed_resend_stays_send_failed_with_the_new_error(self):
        self.fake.submit_error = ClinVarError("ClinVar returned 503", retryable=True)
        batch = self._make(
            status=Batch.Status.SEND_TO_CLINVAR_FAILED, error_message="old error"
        )
        response = self.resend(batch)
        batch.refresh_from_db()
        self.assertEqual(batch.status, Batch.Status.SEND_TO_CLINVAR_FAILED)
        self.assertEqual(batch.error_message, "ClinVar returned 503")
        self.assertContains(response, "ClinVar still didn&#x27;t get the batch.")
        self.assertNotContains(response, "ClinVar returned 503")

    def test_only_send_failed_submissions_can_be_resent(self):
        batch = self._make(
            status=Batch.Status.SUBMITTED_TO_CLINVAR,
            clinvar_submission_id="SUB000005",
        )
        response = self.resend(batch)
        self.assertContains(response, "Only a batch ClinVar never got can be resent.")
        batch.refresh_from_db()
        self.assertEqual(batch.clinvar_submission_id, "SUB000005")
        self.assertEqual(self.fake.submitted, [])

    def test_resend_needs_a_post(self):
        batch = self._make(status=Batch.Status.SEND_TO_CLINVAR_FAILED)
        response = self.client.get(reverse("css:resend", kwargs={"slug": batch.slug}))
        self.assertEqual(response.status_code, 405)


class WithdrawViewTest(CssViewTestCase):
    def _waiting(self, **fields: object) -> Record:
        content = Content.model_validate(make_content())
        return Record.objects.create(**(record_fields(content)[0] | fields))

    def withdraw(self, record: Record):
        return self.client.post(
            reverse("css:withdraw", kwargs={"slug": record.slug}), follow=True
        )

    def test_staff_can_withdraw_a_waiting_record(self):
        record = self._waiting()
        response = self.withdraw(record)
        self.assertRedirects(response, record.get_absolute_url())
        self.assertContains(response, "The record was withdrawn.")
        record.refresh_from_db()
        self.assertEqual(record.status, Record.Status.WITHDRAWN)
        latest = record.history.first()  # type: ignore
        self.assertEqual(latest.history_user, self.user)
        self.assertEqual(latest.history_change_reason, "Withdrawn by staff")

    def test_a_batched_or_accepted_record_cant_be_withdrawn(self):
        for status in [Record.Status.IN_BATCH, Record.Status.SUCCEEDED_AT_CLINVAR]:
            with self.subTest(status):
                record = self._waiting(status=status)
                response = self.withdraw(record)
                self.assertContains(
                    response,
                    "Only a record that&#x27;s waiting for a batch can be withdrawn.",
                )
                record.refresh_from_db()
                self.assertEqual(record.status, status)

    def test_withdraw_needs_a_post(self):
        record = self._waiting()
        response = self.client.get(
            reverse("css:withdraw", kwargs={"slug": record.slug})
        )
        self.assertEqual(response.status_code, 405)


def _settings_url(affiliation_id: int) -> str:
    return reverse(
        "css:affiliation_settings", kwargs={"affiliation_id": affiliation_id}
    )


VALID_SETTINGS = {
    "assertion_criteria_db": "PubMed",
    "assertion_criteria_id": "25741868",
    "behalf_org_id": "506185",
    "release_status": "public",
}


class AffiliationSettingsViewTest(CssViewTestCase):
    def setUp(self):
        super().setUp()
        self._make()  # The CSS knows the Hearing Loss VCEP from its batch.

    def test_shows_the_affiliations_settings(self):
        AffiliationSettings.objects.create(
            affiliation_id=10007, behalf_org_id=506185, release_status="public"
        )
        response = self.client.get(_settings_url(10007))
        self.assertContains(response, "Hearing Loss VCEP")
        self.assertContains(response, 'value="506185"')
        self.assertContains(response, '<option value="public" selected>')

    def test_the_organization_id_is_a_text_field_without_a_spinner(self):
        response = self.client.get(_settings_url(10007))
        self.assertNotContains(response, 'type="number"')
        self.assertContains(response, 'inputmode="numeric"')

    def test_names_an_affiliation_known_only_from_its_records(self):
        content = Content.model_validate(make_content())
        Record.objects.create(
            affiliation_id=10008,
            affiliation_name="Cardiomyopathy VCEP",
            **record_fields(content)[0],
        )
        response = self.client.get(_settings_url(10008))
        self.assertContains(response, "Cardiomyopathy VCEP")

    def test_saves_the_settings_and_who_saved_them(self):
        response = self.client.post(_settings_url(10007), VALID_SETTINGS, follow=True)
        self.assertRedirects(response, _settings_url(10007))
        self.assertContains(response, "Saved the settings for Hearing Loss VCEP.")
        settings = AffiliationSettings.objects.get(affiliation_id=10007)
        self.assertEqual(settings.assertion_criteria_db, "PubMed")
        self.assertEqual(settings.assertion_criteria_id, "25741868")
        self.assertEqual(settings.behalf_org_id, 506185)
        self.assertEqual(settings.release_status, "public")
        self.assertEqual(settings.history.first().history_user, self.user)  # type: ignore

    def test_updates_saved_settings(self):
        AffiliationSettings.objects.create(affiliation_id=10007, behalf_org_id=1)
        self.client.post(_settings_url(10007), VALID_SETTINGS)
        settings = AffiliationSettings.objects.get()
        self.assertEqual(settings.behalf_org_id, 506185)

    def test_rejects_bad_values_with_a_plain_message(self):
        cases = {
            "unknown database": (
                {"assertion_criteria_db": "Wikipedia"},
                "Pick one of the listed choices.",
            ),
            "behalfOrgID below 1": (
                {"behalf_org_id": "0"},
                "Enter ClinVar&#x27;s ID for the organization, a number of 1 or more.",
            ),
            "unknown release status": (
                {"release_status": "secret"},
                "Pick one of the listed choices.",
            ),
            "criteria ID without a database": (
                {"assertion_criteria_db": ""},
                (
                    "Enter both the assertion criteria&#x27;s database and its ID, "
                    "or neither."
                ),
            ),
        }
        for name, (change, message) in cases.items():
            with self.subTest(name):
                response = self.client.post(
                    _settings_url(10007), VALID_SETTINGS | change
                )
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, message)
                self.assertFalse(AffiliationSettings.objects.exists())

    def test_an_unknown_affiliation_is_404(self):
        self.assertEqual(self.client.get(_settings_url(99999)).status_code, 404)

    def test_the_affiliations_page_links_to_the_settings(self):
        response = self.client.get(reverse("css:affiliations"))
        self.assertContains(response, _settings_url(10007))


class RecordListViewTest(CssViewTestCase):
    def _record(self, local_id: str, **fields: object) -> Record:
        content = Content.model_validate(make_content(make_record(local_id)))
        defaults = {
            "affiliation_id": 10007,
            "affiliation_name": "Hearing Loss VCEP",
            "payload": make_record(local_id),
        }
        return Record.objects.create(**(record_fields(content)[0] | defaults | fields))

    def test_lists_records_newest_first(self):
        older, newer = self._record("var-1"), self._record("var-2")
        response = self.client.get(reverse("css:records"))
        self.assertTemplateUsed(response, "clinvar_submission_service/records.html")
        self.assertEqual(_listed(response), [newer, older])
        self.assertContains(response, "2 records")
        self.assertContains(response, "BRCA1")
        self.assertContains(response, "Likely Pathogenic")

    def test_never_shows_raw_json(self):
        self._record("var-1")
        response = self.client.get(reverse("css:records"))
        self.assertNotContains(response, "germlineClassificationDescription")

    def test_filters_by_status_with_pills(self):
        waiting = self._record("var-1")
        self._record("var-2", status=Record.Status.WITHDRAWN)
        response = self.client.get(
            reverse("css:records"), {"status": "waiting_for_batch"}
        )
        self.assertEqual(_listed(response), [waiting])
        for label in ["All", "Waiting", "In a Batch", "Success", "Withdrawn"]:
            with self.subTest(label):
                self.assertContains(response, f">{label}</a>")
        self.assertContains(response, 'href="?status=withdrawn"')

    def test_an_unknown_status_shows_every_record(self):
        self._record("var-1")
        response = self.client.get(reverse("css:records"), {"status": "lost"})
        self.assertEqual(len(_listed(response)), 1)

    def test_filters_by_affiliation(self):
        ours = self._record("var-1")
        self._record("var-2", affiliation_id=10008, affiliation_name="TP53 VCEP")
        response = self.client.get(reverse("css:records"), {"affiliation": "10007"})
        self.assertEqual(_listed(response), [ours])
        self.assertContains(
            response, '<option value="10007" selected>Hearing Loss VCEP</option>'
        )
        self.assertContains(response, '<option value="10008">TP53 VCEP</option>')
        response = self.client.get(reverse("css:records"), {"affiliation": "VCEP"})
        self.assertEqual(_listed(response), [])

    def test_searches_by_gene_hgvs_local_id_or_affiliation(self):
        match = self._record("vci-123", gene_symbol="MYH7", hgvs="NM_000257.4:c.1A>G")
        self._record("var-2", affiliation_name="TP53 VCEP")
        for query in ["myh7", "c.1A>G", "vci-123", "Hearing"]:
            with self.subTest(query):
                response = self.client.get(reverse("css:records"), {"q": query})
                self.assertEqual(_listed(response), [match])

    def test_each_status_tag_links_to_its_filter(self):
        self._record("var-1", status=Record.Status.IN_BATCH)
        response = self.client.get(reverse("css:records"), {"affiliation": "10007"})
        self.assertContains(response, 'href="?affiliation=10007&amp;status=in_batch"')
        self.assertContains(response, "This record is in a batch")

    def test_an_htmx_request_gets_only_the_results(self):
        self._record("var-1")
        response = self.client.get(
            reverse("css:records"), headers={"HX-Request": "true"}
        )
        self.assertTemplateUsed(
            response, "clinvar_submission_service/partials/record_results.html"
        )
        self.assertTemplateNotUsed(response, "clinvar_submission_service/records.html")


def _new_batch_url(affiliation_id: int) -> str:
    return reverse("css:new_batch", kwargs={"affiliation_id": affiliation_id})


class NewBatchViewTest(CssViewTestCase):
    def setUp(self):
        super().setUp()
        self.fake = FakeClinVarClient()
        patcher = mock.patch(
            "clinvar_submission_service.services.ClinVarClient.from_settings",
            return_value=self.fake,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        self.first = self._record("var-1")
        self.second = self._record("var-2")

    def _record(self, local_id: str, **fields: object) -> Record:
        content = Content.model_validate(make_content(make_record(local_id)))
        defaults = {
            "affiliation_id": 10007,
            "affiliation_name": "Hearing Loss VCEP",
            "payload": make_record(local_id),
        }
        return Record.objects.create(**(record_fields(content)[0] | defaults | fields))

    def post(self, action: str, *records: Record, **extra: object):
        data = {"action": action, "records": [r.slug for r in records]}
        return self.client.post(_new_batch_url(10007), data | extra, follow=True)

    def test_lists_the_affiliations_waiting_records_to_pick(self):
        withdrawn = self._record("var-3", status=Record.Status.WITHDRAWN)
        theirs = self._record("var-4", affiliation_id=10008)
        response = self.client.get(_new_batch_url(10007))
        self.assertContains(response, "Hearing Loss VCEP")
        for record in (self.first, self.second):
            self.assertContains(response, f'value="{record.slug}"')
        for record in (withdrawn, theirs):
            self.assertNotContains(response, record.slug)
        self.assertContains(response, "Add Every Waiting Record")

    def test_reviews_the_chosen_records_before_sending(self):
        response = self.post("review", self.second)
        self.assertContains(response, "Review the Batch")
        self.assertContains(response, f'value="{self.second.slug}"')
        self.assertNotContains(response, self.first.slug)
        self.assertContains(response, "Send to ClinVar")
        self.assertFalse(Batch.objects.exists())

    def test_the_shortcut_reviews_every_waiting_record(self):
        response = self.post("review_all")
        for record in (self.first, self.second):
            self.assertContains(response, f'value="{record.slug}"')
        self.assertFalse(Batch.objects.exists())

    def test_sending_makes_and_sends_the_batch(self):
        response = self.post("send", self.first, self.second)
        batch = Batch.objects.get()
        self.assertRedirects(response, batch.get_absolute_url())
        self.assertEqual(
            list(batch.records.order_by("batch_records")), [self.first, self.second]
        )
        self.assertEqual(batch.status, Batch.Status.SUBMITTED_TO_CLINVAR)
        self.assertEqual(len(self.fake.submitted), 1)
        self.assertContains(response, "var-1")
        self.assertContains(response, "var-2")
        self.assertEqual(batch.made_by, self.user)

    def test_refuses_an_empty_or_mixed_selection_with_a_plain_message(self):
        theirs = self._record("var-3", affiliation_id=10008)
        cases = {
            "empty review": ("review", [], "Pick at least one record."),
            "empty send": ("send", [], "Pick at least one record."),
            "mixed": (
                "send",
                [self.first, theirs],
                "A batch can hold only one affiliation&#x27;s records.",
            ),
            "not waiting": (
                "review",
                [self._record("var-4", status=Record.Status.IN_BATCH)],
                "Only records waiting for a batch can be added to one.",
            ),
        }
        for name, (action, records, message) in cases.items():
            with self.subTest(name):
                response = self.post(action, *records)
                self.assertContains(response, message)
                self.assertContains(response, "Add Every Waiting Record")
        self.assertFalse(Batch.objects.exists())
        self.assertEqual(self.fake.submitted, [])

    def test_an_unknown_affiliation_is_404(self):
        self.assertEqual(self.client.get(_new_batch_url(99999)).status_code, 404)

    def test_the_records_list_links_to_it_for_one_affiliation(self):
        response = self.client.get(reverse("css:records"), {"affiliation": "10007"})
        self.assertContains(response, _new_batch_url(10007))
        response = self.client.get(reverse("css:records"))
        self.assertNotContains(response, _new_batch_url(10007))


class RecordDetailViewTest(CssViewTestCase):
    def _record(self, **fields: object) -> Record:
        content = Content.model_validate(
            make_content(make_record("var-1", recordStatus="novel"))
        )
        defaults = {
            "api_key": self.api_key,
            "affiliation_id": 10007,
            "affiliation_name": "Hearing Loss VCEP",
            "payload": make_record("var-1"),
        }
        return Record.objects.create(**(record_fields(content)[0] | defaults | fields))

    def test_shows_the_records_fields_and_status(self):
        record = self._record()
        response = self.client.get(record.get_absolute_url())
        self.assertTemplateUsed(response, "clinvar_submission_service/record.html")
        for text in [
            "var-1",
            "Hearing Loss VCEP",
            "GCI",
            "BRCA1",
            "NC_000017.11:g.43045712T&gt;C",
            "MONDO:0011450",
            "Likely Pathogenic",
            "Criteria met: PM2, PS3, PP3.",
            "Waiting",
            "waiting to be added to a batch",
        ]:
            with self.subTest(text):
                self.assertContains(response, text)

    def test_lists_each_attempt_with_its_batch_result_and_scv(self):
        record = self._record(
            status=Record.Status.SUCCEEDED_AT_CLINVAR,
            clinvar_accession="SCV000000001",
        )
        failed = Batch.objects.create(status=Batch.Status.ERROR_AT_CLINVAR)
        BatchRecord.objects.create(
            batch=failed,
            record=record,
            position=0,
            result="Error",
            errors=[{"output": {"errors": [{"userMessage": "Duplicate record."}]}}],
        )
        accepted = Batch.objects.create(status=Batch.Status.PROCESSED_BY_CLINVAR)
        BatchRecord.objects.create(
            batch=accepted,
            record=record,
            position=0,
            result="Success",
            scv="SCV000000001",
        )
        response = self.client.get(record.get_absolute_url())
        self.assertContains(response, failed.get_absolute_url())
        self.assertContains(response, accepted.get_absolute_url())
        self.assertContains(response, "SCV000000001")
        self.assertContains(response, ">Error<")
        self.assertContains(response, ">Success<")
        self.assertNotContains(response, "Duplicate record.")

    def test_shows_its_history_in_plain_words(self):
        record = self._record()
        withdraw_record(record, by="staff")
        response = self.client.get(record.get_absolute_url())
        self.assertContains(response, "Received from the GCI")
        self.assertContains(response, "Withdrawn by staff")

    def test_only_a_waiting_record_has_a_withdraw_button(self):
        for status, shown in [
            (Record.Status.WAITING_FOR_BATCH, True),
            (Record.Status.IN_BATCH, False),
            (Record.Status.SUCCEEDED_AT_CLINVAR, False),
            (Record.Status.WITHDRAWN, False),
        ]:
            with self.subTest(status):
                record = self._record(status=status)
                response = self.client.get(record.get_absolute_url())
                withdraw_url = reverse("css:withdraw", kwargs={"slug": record.slug})
                if shown:
                    self.assertContains(response, withdraw_url)
                else:
                    self.assertNotContains(response, withdraw_url)

    def test_never_shows_raw_json(self):
        record = self._record()
        response = self.client.get(record.get_absolute_url())
        self.assertNotContains(response, "germlineClassificationDescription")

    def test_the_records_list_and_batch_page_link_to_it(self):
        batch = self._make(make_record("var-9"))
        record = batch.records.get()
        for url in [reverse("css:records"), batch.get_absolute_url()]:
            with self.subTest(url):
                self.assertContains(
                    self.client.get(url), f'href="{record.get_absolute_url()}"'
                )

    def test_unknown_slug_is_404(self):
        response = self.client.get(reverse("css:record", kwargs={"slug": "Rmissing"}))
        self.assertEqual(response.status_code, 404)


class AffiliationSelectTest(CssViewTestCase):
    def _waiting(self, affiliation_id: int, name: str, **fields: object) -> Record:
        content = Content.model_validate(make_content())
        return Record.objects.create(
            affiliation_id=affiliation_id,
            affiliation_name=name,
            **(record_fields(content)[0] | fields),
        )

    def test_each_list_offers_every_known_affiliation_by_name(self):
        self._waiting(10008, "TP53 VCEP")
        self._make()  # Hearing Loss VCEP, 10007, known from its batch.
        for url in [reverse("css:records"), reverse("css:batches")]:
            with self.subTest(url):
                html = self.client.get(url).content.decode()
                self.assertIn(
                    '<option value="" selected>All affiliations</option>', html
                )
                self.assertLess(
                    html.index(">Hearing Loss VCEP</option>"),
                    html.index(">TP53 VCEP</option>"),
                )

    def test_the_select_keeps_the_status_and_search(self):
        self._waiting(10007, "Hearing Loss VCEP")
        for url, status in [
            (reverse("css:records"), "withdrawn"),
            (reverse("css:batches"), "error_at_clinvar"),
        ]:
            with self.subTest(url):
                response = self.client.get(url, {"status": status, "q": "BRCA1"})
                self.assertContains(response, 'name="affiliation"')
                self.assertContains(
                    response, f'<input type="hidden" name="status" value="{status}">'
                )
                self.assertContains(response, 'value="BRCA1"')

    def test_new_batch_shows_for_one_affiliation_with_waiting_records(self):
        self._waiting(10007, "Hearing Loss VCEP")
        self._waiting(10008, "TP53 VCEP", status=Record.Status.WITHDRAWN)
        for url in [reverse("css:records"), reverse("css:batches")]:
            with self.subTest(url):
                response = self.client.get(url, {"affiliation": "10007"})
                self.assertContains(response, _new_batch_url(10007))
                response = self.client.get(url, {"affiliation": "10008"})
                self.assertNotContains(response, _new_batch_url(10008))
                response = self.client.get(url)
                self.assertNotContains(response, _new_batch_url(10007))


class AffiliationTestCase(TestCase):
    fixtures = ["test_batches.json"]

    def setUp(self):
        self.client.force_login(_make_user("staff@example.com", css=True))


class AffiliationFilterTest(AffiliationTestCase):
    def test_filters_the_list_to_one_affiliation(self):
        response = self.client.get(reverse("css:batches"), {"affiliation": "10901"})
        names = {s.affiliation_name for s in _listed(response)}
        self.assertEqual(names, {"Cardiomyopathy VCEP"})
        self.assertEqual(len(_listed(response)), 3)
        self.assertContains(
            response, '<option value="10901" selected>Cardiomyopathy VCEP</option>'
        )

    def test_combines_with_the_status_filter(self):
        response = self.client.get(
            reverse("css:batches"),
            {"affiliation": "10901", "status": "not_sent_to_clinvar"},
        )
        self.assertEqual(
            [s.status for s in _listed(response)],
            [Batch.Status.NOT_SENT_TO_CLINVAR],
        )
        self.assertContains(
            response, 'href="?affiliation=10901&amp;status=processed_by_clinvar"'
        )

    def test_an_unknown_affiliation_shows_nothing(self):
        for value in ("99999", "not-a-number"):
            with self.subTest(value=value):
                response = self.client.get(
                    reverse("css:batches"), {"affiliation": value}
                )
                self.assertEqual(_listed(response), [])
                self.assertContains(response, "No affiliation has that ID.")


class AffiliationsViewTest(AffiliationTestCase):
    def test_needs_css_permissions(self):
        self.client.force_login(_make_user("other@example.com"))
        response = self.client.get(reverse("css:affiliations"))
        self.assertEqual(response.status_code, 403)

    def test_counts_each_affiliations_records_and_batches_by_pill(self):
        response = self.client.get(reverse("css:affiliations"))
        self.assertTemplateUsed(
            response, "clinvar_submission_service/affiliations.html"
        )
        counts = {
            row["name"]: (
                tuple(count for _, count, _ in row["records"]),
                tuple(count for _, count, _ in row["batches"]),
            )
            for row in response.context["affiliations"]
        }
        self.assertEqual(
            counts,
            {
                "CDH1 VCEP": ((3, 1, 0, 2, 0), (1, 0, 0, 0, 0, 0, 1)),
                "Cardiomyopathy VCEP": ((5, 2, 2, 1, 0), (3, 1, 0, 0, 1, 1, 0)),
                "Malignant Hyperthermia Susceptibility VCEP": (
                    (1, 0, 1, 0, 0),
                    (1, 0, 0, 1, 0, 0, 0),
                ),
                "Phenylketonuria VCEP": ((2, 0, 0, 2, 0), (1, 0, 0, 0, 0, 1, 0)),
                "TP53 VCEP": ((3, 0, 2, 0, 1), (2, 0, 1, 0, 0, 0, 1)),
            },
        )

    def test_lists_an_affiliation_known_only_from_its_records(self):
        content = Content.model_validate(make_content())
        Record.objects.create(
            affiliation_id=10999,
            affiliation_name="Hearing Loss VCEP",
            **record_fields(content)[0],
        )
        response = self.client.get(reverse("css:affiliations"))
        rows = {row["name"]: row for row in response.context["affiliations"]}
        self.assertEqual(rows["Hearing Loss VCEP"]["records"][0][1], 1)
        self.assertEqual(rows["Hearing Loss VCEP"]["batches"][0][1], 0)

    def test_lists_affiliations_by_name(self):
        response = self.client.get(reverse("css:affiliations"))
        names = [row["name"] for row in response.context["affiliations"]]
        self.assertEqual(names, sorted(names))

    def test_the_columns_match_each_lists_pills(self):
        html = self.client.get(reverse("css:affiliations")).content.decode()
        head = html[html.index("<thead>") : html.index("</thead>")]
        labels = [
            "Affiliation",
            "Records",
            "Batches",
            "All",
            *Record.Status.labels,
            "All",
            *Batch.Status.labels,
        ]
        positions = []
        start = 0
        for label in labels:
            start = head.index(f">{label}<", start)
            positions.append(start)
        self.assertEqual(positions, sorted(positions))

    def test_each_count_links_to_its_filtered_list(self):
        response = self.client.get(reverse("css:affiliations"))
        records, batches = reverse("css:records"), reverse("css:batches")
        for href in [
            f"{records}?affiliation=10901",
            f"{records}?affiliation=10901&amp;status=waiting_for_batch",
            f"{batches}?affiliation=10901",
            f"{batches}?affiliation=10901&amp;status=error_at_clinvar",
        ]:
            with self.subTest(href):
                self.assertContains(response, f'href="{href}"')

    def test_settings_is_a_labeled_gear(self):
        response = self.client.get(reverse("css:affiliations"))
        self.assertContains(
            response,
            f'<a href="{_settings_url(10901)}" '
            'title="Settings for Cardiomyopathy VCEP">',
        )
        self.assertContains(response, "bi-gear")
        self.assertContains(
            response, '<span class="is-sr-only">Settings for Cardiomyopathy VCEP</span>'
        )


def _between(html: str, start: str, end: str) -> str:
    """Returns the part of the HTML from start to the next end."""
    begin = html.index(start)
    return html[begin : html.index(end, begin)]


def _breadcrumbs(response: "Response") -> list[tuple[str, str]]:
    """Returns each breadcrumb's text and link; the current page's link is ""."""
    nav = _between(response.content.decode(), '<nav class="breadcrumb"', "</nav>")
    crumbs = []
    for item in re.findall(r"<li[^>]*>(.*?)</li>", nav, re.S):
        current = 'aria-current="page"' in item
        link = re.search(r'href="([^"]*)"', item)
        href = "" if current or link is None else link.group(1)
        text = " ".join(re.sub(r"<[^>]+>", " ", item).split())
        crumbs.append((text, href))
    return crumbs


class NavigationTest(CssViewTestCase):
    def setUp(self):
        super().setUp()
        self.batch = self._make(make_record())
        self.record = self.batch.records.get()
        Record.objects.filter(pk=self.record.pk).update(
            affiliation_id=10007, affiliation_name="Hearing Loss VCEP"
        )

    def pages(self) -> dict[str, tuple[str, str, list[tuple[str, str]]]]:
        """Returns each page's URL, section, and breadcrumbs, by name."""
        records, batches = reverse("css:records"), reverse("css:batches")
        affiliations = reverse("css:affiliations")
        return {
            "affiliations": (affiliations, "Affiliations", [("Affiliations", "")]),
            "settings": (
                _settings_url(10007),
                "Affiliations",
                [("Affiliations", affiliations), ("Hearing Loss VCEP Settings", "")],
            ),
            "records": (records, "Records", [("Records", "")]),
            "record": (
                self.record.get_absolute_url(),
                "Records",
                [("Records", records), (f"{self.record.slug} Details", "")],
            ),
            "new batch": (
                _new_batch_url(10007),
                "Records",
                [("Records", records), ("New Batch", "")],
            ),
            "batches": (batches, "Batches", [("Batches", "")]),
            "batch": (
                self.batch.get_absolute_url(),
                "Batches",
                [("Batches", batches), (f"{self.batch.slug} Details", "")],
            ),
        }

    def test_each_page_has_its_breadcrumbs(self):
        for name, (url, _, crumbs) in self.pages().items():
            with self.subTest(name):
                self.assertEqual(_breadcrumbs(self.client.get(url)), crumbs)

    def test_the_navbar_links_to_each_section_and_marks_the_current_one(self):
        sections = {
            "Records": reverse("css:records"),
            "Batches": reverse("css:batches"),
            "Affiliations": reverse("css:affiliations"),
        }
        for name, (url, section, _) in self.pages().items():
            with self.subTest(name):
                html = self.client.get(url).content.decode()
                navbar = _between(
                    html, '<nav class="navbar" aria-label="CSS"', "</nav>"
                )
                hrefs = [navbar.index(f'href="{href}"') for href in sections.values()]
                self.assertEqual(hrefs, sorted(hrefs))
                bold = re.findall(
                    r'<a href="([^"]*)" class="navbar-item has-text-weight-bold"',
                    navbar,
                )
                self.assertEqual(bold, [sections[section]])
                self.assertLess(html.index('<h2 class="subtitle">'), html.index(navbar))

    def test_no_page_has_the_old_tabs(self):
        for name, (url, _, _) in self.pages().items():
            with self.subTest(name):
                self.assertNotContains(self.client.get(url), "tabs is-boxed")
