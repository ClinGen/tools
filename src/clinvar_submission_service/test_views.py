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
from clinvar_submission_service.views import PAGE_SIZE

if TYPE_CHECKING:
    from django.test.client import _MonkeyPatchedWSGIResponse as Response

REPORT = {
    "totalCount": 2,
    "totalErrors": 1,
    "totalSuccess": 1,
    "batches": [
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


def _listed(response: "Response") -> list[Batch]:
    """Returns the batches on the list page's current page, in order."""
    return [row.record for row in response.context["table"].paginated_rows]


class CssViewTestCase(TestCase):
    def setUp(self):
        self.user = _make_user("staff@example.com", css=True)
        self.client.force_login(self.user)
        self.api_key, _ = ApiKey.objects.create_key(name="GCI")

    def _make(self, *records: dict, **fields: object) -> Batch:
        """Returns a batch from the Hearing Loss VCEP with the given records."""
        payload = make_content(*records) if records else {}
        defaults = {"affiliation_id": 10007, "affiliation_name": "Hearing Loss VCEP"}
        batch = Batch.objects.create(api_key=self.api_key, **(defaults | fields))
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
            ("get", reverse("css:index")),
            ("get", batch.get_absolute_url()),
            ("post", reverse("css:resend", kwargs={"slug": batch.slug})),
            ("post", reverse("css:withdraw", kwargs={"slug": record.slug})),
            ("get", _settings_url(10007)),
            ("post", _settings_url(10007)),
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

    def test_filters_to_each_status(self):
        by_status = {
            status: self._make(status=status) for status in Batch.Status.values
        }
        for status, batch in by_status.items():
            with self.subTest(status=status):
                response = self.client.get(reverse("css:index"), {"status": status})
                self.assertEqual(_listed(response), [batch])
        for status in ("", "received", "unknown"):
            with self.subTest(status=status):
                response = self.client.get(reverse("css:index"), {"status": status})
                self.assertEqual(set(_listed(response)), set(by_status.values()))

    def test_has_a_pill_for_all_and_each_status(self):
        response = self.client.get(reverse("css:index"))
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
            reverse("css:index"), {"status": "submitted_to_clinvar"}
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
                response = self.client.get(reverse("css:index"), {"q": query})
                self.assertEqual(_listed(response), [match])

    def test_search_keeps_the_filter(self):
        self._make(
            status=Batch.Status.SUBMITTED_TO_CLINVAR, clinvar_submission_id="SUB1"
        )
        response = self.client.get(
            reverse("css:index"), {"q": "SUB1", "status": "not_sent_to_clinvar"}
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
                response = self.client.get(reverse("css:index"), {"sort": sort})
                self.assertEqual(_listed(response), expected)

    def test_page_links_keep_the_search_and_filters(self):
        for _ in range(PAGE_SIZE + 1):
            self._make(status=Batch.Status.NOT_SENT_TO_CLINVAR)
        params = {
            "q": "Hearing",
            "status": "not_sent_to_clinvar",
            "affiliation": "10007",
        }
        response = self.client.get(reverse("css:index"), params)
        self.assertContains(
            response,
            "?q=Hearing&amp;status=not_sent_to_clinvar&amp;affiliation=10007&amp;page=2",
        )

    def test_an_htmx_request_gets_only_the_results(self):
        self._make()
        response = self.client.get(reverse("css:index"), HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(
            response, "clinvar_submission_service/partials/results.html"
        )
        self.assertTemplateNotUsed(response, "clinvar_submission_service/list.html")
        self.assertContains(response, "1 batch")

    def test_the_search_box_sends_the_filters_as_you_type(self):
        response = self.client.get(reverse("css:index"), {"affiliation": "10007"})
        self.assertContains(response, 'hx-include="closest form"')
        self.assertContains(response, 'name="affiliation" value="10007"')

    def test_says_when_the_css_received_each_batch(self):
        self._make()
        self.assertContains(self.client.get(reverse("css:index")), "Received by CSS")

    def test_says_so_when_there_are_none(self):
        response = self.client.get(reverse("css:index"))
        self.assertContains(response, "No batches yet.")

    def test_has_the_header_with_the_list_tab_active(self):
        response = self.client.get(reverse("css:index"))
        self.assertContains(response, "ClinVar Submission Service")
        self.assertContains(
            response,
            f'<a href="{reverse("css:index")}" aria-current="page">',
        )


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
        response = self.client.get(reverse("css:index"))
        self.assertContains(response, f'data-tippy-content="{escape(help_text)}"')

    def test_each_tag_in_the_list_links_to_its_status(self):
        for status in Batch.Status.values:
            self._make(status=status)
        html = self.client.get(reverse("css:index")).content.decode()
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
        response = self.client.get(reverse("css:index"), {"affiliation": "10007"})
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
        pages = [reverse("css:index"), reverse("css:affiliations")]
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
        self.assertContains(response, "GCI")
        self.assertContains(response, "Hearing Loss VCEP")
        self.assertContains(response, f"Batch {batch.slug}")

    def test_the_batch_tab_comes_between_submissions_and_affiliations(self):
        batch = self._make()
        html = self.client.get(batch.get_absolute_url()).content.decode()
        tabs = ["Batches", f"Batch {batch.slug}", "Affiliations"]
        positions = [html.index(f"<span>{tab}</span>") for tab in tabs]
        self.assertEqual(positions, sorted(positions))

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
        self.assertRedirects(response, reverse("css:index"))
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


class AffiliationTestCase(TestCase):
    fixtures = ["test_batches.json"]

    def setUp(self):
        self.client.force_login(_make_user("staff@example.com", css=True))


class AffiliationFilterTest(AffiliationTestCase):
    def test_filters_the_list_to_one_affiliation(self):
        response = self.client.get(reverse("css:index"), {"affiliation": "10901"})
        names = {s.affiliation_name for s in _listed(response)}
        self.assertEqual(names, {"Cardiomyopathy VCEP"})
        self.assertEqual(len(_listed(response)), 3)
        self.assertContains(response, "Showing batches from Cardiomyopathy VCEP.")

    def test_combines_with_the_status_filter(self):
        response = self.client.get(
            reverse("css:index"),
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
                response = self.client.get(reverse("css:index"), {"affiliation": value})
                self.assertEqual(_listed(response), [])


class AffiliationsViewTest(AffiliationTestCase):
    def test_needs_css_permissions(self):
        self.client.force_login(_make_user("other@example.com"))
        response = self.client.get(reverse("css:affiliations"))
        self.assertEqual(response.status_code, 403)

    def test_counts_each_affiliations_batches(self):
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

    def test_lists_affiliations_by_name_with_links_to_their_batches(self):
        response = self.client.get(reverse("css:affiliations"))
        names = [row["name"] for row in response.context["affiliations"]]
        self.assertEqual(names, sorted(names))
        self.assertContains(response, f"{reverse('css:index')}?affiliation=10901")

    def test_the_headers_use_clinvars_wording(self):
        response = self.client.get(reverse("css:affiliations"))
        for header in (
            "Not Sent or Send Failed",
            "Submitted or Processing",
            "Processed",
            "Error",
        ):
            with self.subTest(header=header):
                self.assertContains(response, f'">{header}<span class="is-sr-only">')
        self.assertNotContains(response, "bi-info-circle")

    def test_the_header_has_an_affiliations_tab(self):
        response = self.client.get(reverse("css:affiliations"))
        self.assertContains(
            response, f'<a href="{reverse("css:affiliations")}" aria-current="page">'
        )
