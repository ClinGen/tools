from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponseBase
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape

from auth_.models import UserProfile
from core.tools import get_tool
from email_transfer_service.clients import CognitoUser, UserRecord
from email_transfer_service.fakes import FakeEtsClient
from email_transfer_service.models import EmailTransfer
from email_transfer_service.transfers import Plan, check_preconditions, run_transfer

OLD = "old@example.com"
NEW = "new@example.com"

# Words that only developers understand, which the ETS's pages shouldn't show.
TECHNICAL_WORDS = [
    "Cognito",
    "DynamoDB",
    "user_status",
    "requested activation",
    "old-pk",
    "new-pk",
    "old-user",
    "new-user",
]


def _client(
    *,
    old_user: bool = True,
    new_user: bool = True,
    new_enabled: bool = False,
    old_record: bool = True,
    new_record_status: str | None = None,
    fail_on: str = "",
) -> FakeEtsClient:
    """Returns a fake client set up for a transfer from OLD to NEW."""
    users = []
    if old_user:
        users.append(CognitoUser(username="old-user", email=OLD, enabled=True))
    if new_user:
        users.append(CognitoUser(username="new-user", email=NEW, enabled=new_enabled))
    records = []
    if old_record:
        records.append(UserRecord(pk="old-pk", email=OLD, user_status="active"))
    if new_record_status is not None:
        records.append(
            UserRecord(pk="new-pk", email=NEW, user_status=new_record_status)
        )
    return FakeEtsClient(users=users, records=records, fail_on=fail_on)


class CheckPreconditionsTest(TestCase):
    def test_plan_without_a_new_record(self):
        preview = check_preconditions(_client(), OLD, NEW)
        self.assertEqual(preview.failures, [])
        self.assertEqual(
            [step.name for step in preview.plan.steps()],  # type: ignore
            ["update_old_record", "disable_old_user", "enable_new_user"],
        )

    def test_plan_retires_a_requested_activation_record(self):
        preview = check_preconditions(
            _client(new_record_status="requested activation"),
            OLD,
            NEW,
        )
        self.assertEqual(preview.failures, [])
        steps = preview.plan.steps()  # type: ignore
        self.assertEqual(steps[0].name, "retire_new_record")
        self.assertIn("new-pk", steps[0].description)
        self.assertEqual(
            steps[0].summary,
            f"Remove the empty GCI/VCI profile that was made for {NEW}.",
        )

    def test_any_other_new_record_status_fails(self):
        preview = check_preconditions(_client(new_record_status="active"), OLD, NEW)
        self.assertIsNone(preview.plan)
        self.assertEqual(
            preview.failures,
            [
                (
                    f"{NEW} already has its own GCI/VCI profile, so the ETS can't move "
                    "another one onto it. Ask a developer for help."
                ),
            ],
        )

    def test_reports_every_failure(self):
        preview = check_preconditions(
            _client(old_user=False, new_user=False, old_record=False),
            OLD,
            NEW,
        )
        self.assertIsNone(preview.plan)
        self.assertEqual(
            preview.failures,
            [
                f"{OLD} has no sign-in account.",
                f"{OLD} has no GCI/VCI profile.",
                (
                    f"{NEW} has no sign-in account. The user needs to sign in to the "
                    "GCI or VCI with it once before the transfer."
                ),
            ],
        )

    def test_already_enabled_new_user_is_skipped(self):
        preview = check_preconditions(_client(new_enabled=True), OLD, NEW)
        enable = preview.plan.steps()[-1]  # type: ignore
        self.assertEqual(enable.name, "enable_new_user")
        self.assertEqual(enable.skip_reason, "Sign-in is already on for this email.")

    def test_descriptions_name_the_users_and_records(self):
        preview = check_preconditions(
            _client(new_record_status="requested activation"),
            OLD,
            NEW,
        )
        descriptions = " ".join(
            step.description
            for step in preview.plan.steps()  # type: ignore
        )
        for name in ["new-pk", "old-pk", "old-user", "new-user", NEW]:
            self.assertIn(name, descriptions)

    def test_summaries_and_failures_have_no_technical_details(self):
        plan = check_preconditions(
            _client(new_record_status="requested activation", new_enabled=True),
            OLD,
            NEW,
        ).plan
        failures = check_preconditions(
            _client(old_user=False, new_user=False, new_record_status="active"),
            OLD,
            NEW,
        ).failures
        plain = [
            *[step.summary for step in plan.steps()],  # type: ignore
            *[step.skip_reason for step in plan.steps()],  # type: ignore
            *failures,
        ]
        for text in plain:
            for word in TECHNICAL_WORDS:
                self.assertNotIn(word, text)


def _sign_in(client: object) -> None:
    user = User.objects.create_user(username="staff@example.com")
    UserProfile.objects.create(user=user, has_ets_permissions=True)
    client.force_login(user)  # type: ignore


class PreviewViewTest(TestCase):
    def setUp(self):
        _sign_in(self.client)
        patcher = mock.patch("email_transfer_service.views.EtsClient.from_settings")
        self.from_settings = patcher.start()
        self.addCleanup(patcher.stop)

    def test_invalid_form_shows_errors(self):
        response = self.client.post(
            reverse("ets:index"),
            {"old_email": OLD, "new_email": OLD},
        )
        self.assertContains(response, "The old and new emails must differ.")
        self.from_settings.assert_not_called()

    def test_failed_preconditions_have_no_confirm_button(self):
        self.from_settings.return_value = _client(old_record=False)
        response = self.client.post(
            reverse("ets:index"),
            {"old_email": OLD, "new_email": NEW},
        )
        self.assertContains(response, "has no GCI/VCI profile")
        self.assertNotContains(response, "Confirm Transfer")

    def test_valid_preview_lists_the_steps(self):
        self.from_settings.return_value = _client(
            new_record_status="requested activation"
        )
        response = self.client.post(
            reverse("ets:index"),
            {"old_email": OLD, "new_email": NEW},
        )
        self.assertContains(response, "Remove the empty GCI/VCI profile")
        self.assertContains(response, f"Turn off sign-in for {OLD}.")
        self.assertContains(response, "Confirm Transfer")
        for word in TECHNICAL_WORDS:
            self.assertNotContains(response, word)

    def test_aws_errors_are_flashed(self):
        self.from_settings.side_effect = ImproperlyConfigured("no user pool")
        response = self.client.post(
            reverse("ets:index"),
            {"old_email": OLD, "new_email": NEW},
        )
        self.assertContains(
            response,
            "The ETS couldn&#x27;t look up these emails. Try again in a few minutes, "
            "or ask a developer for help.",
        )
        self.assertNotContains(response, "no user pool")
        self.assertNotContains(response, "Confirm Transfer")

    @override_settings(ETS_DRY_RUN=True)
    def test_dry_run_banner(self):
        response = self.client.get(reverse("ets:index"))
        self.assertContains(response, "Dry-run mode is on.")


def _plan(client: FakeEtsClient) -> Plan:
    """Returns the plan for a transfer from OLD to NEW."""
    preview = check_preconditions(client, OLD, NEW)
    assert preview.plan
    return preview.plan


class RunTransferTest(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="staff@example.com")

    def _results(self, transfer: EmailTransfer) -> list[str]:
        return [step["result"] for step in transfer.steps]

    def test_full_success(self):
        client = _client()
        transfer = run_transfer(client, _plan(client), ran_by=self.staff, dry_run=False)
        self.assertEqual(transfer.status, EmailTransfer.Status.SUCCEEDED)
        self.assertFalse(transfer.dry_run)
        self.assertEqual(transfer.ran_by, self.staff)
        self.assertEqual(
            client.calls,
            [
                ("update_record_email", "old-pk", NEW),
                ("disable_cognito_user", "old-user"),
                ("enable_cognito_user", "new-user"),
            ],
        )
        self.assertEqual(self._results(transfer), ["succeeded"] * 3)
        self.assertEqual(transfer.old_username, "old-user")
        self.assertEqual(transfer.new_username, "new-user")
        self.assertEqual(transfer.old_record_pk, "old-pk")
        self.assertEqual(transfer.retired_record_pk, "")
        self.assertIn("old-pk", transfer.steps[0]["description"])

    def test_requested_activation_record_is_retired_first(self):
        client = _client(new_record_status="requested activation")
        transfer = run_transfer(client, _plan(client), ran_by=self.staff, dry_run=False)
        self.assertEqual(client.calls[0], ("retire_record", "new-pk"))
        self.assertEqual(transfer.retired_record_pk, "new-pk")
        self.assertEqual(self._results(transfer), ["succeeded"] * 4)

    def test_already_enabled_new_user_is_skipped(self):
        client = _client(new_enabled=True)
        transfer = run_transfer(client, _plan(client), ran_by=self.staff, dry_run=False)
        self.assertNotIn(("enable_cognito_user", "new-user"), client.calls)
        self.assertEqual(self._results(transfer)[-1], "skipped")
        self.assertEqual(transfer.status, EmailTransfer.Status.SUCCEEDED)

    def test_failure_at_each_step_stops_the_transfer(self):
        writes = [
            "retire_record",
            "update_record_email",
            "disable_cognito_user",
            "enable_cognito_user",
        ]
        for index, write in enumerate(writes):
            with self.subTest(write=write):
                client = _client(
                    new_record_status="requested activation",
                    fail_on=write,
                )
                transfer = run_transfer(
                    client,
                    _plan(client),
                    ran_by=self.staff,
                    dry_run=False,
                )
                self.assertEqual(transfer.status, EmailTransfer.Status.FAILED)
                self.assertEqual(transfer.error, f"{write} failed")
                self.assertEqual(transfer.steps[index]["error"], f"{write} failed")
                self.assertEqual(
                    self._results(transfer),
                    ["succeeded"] * index + ["failed"] + ["not run"] * (3 - index),
                )
                self.assertEqual(len(client.calls), index)
                transfer.refresh_from_db()
                self.assertEqual(transfer.status, EmailTransfer.Status.FAILED)

    def test_dry_run_makes_no_writes(self):
        client = _client(new_record_status="requested activation")
        transfer = run_transfer(client, _plan(client), ran_by=self.staff, dry_run=True)
        self.assertEqual(client.calls, [])
        self.assertTrue(transfer.dry_run)
        self.assertEqual(transfer.status, EmailTransfer.Status.SUCCEEDED)
        self.assertEqual(self._results(transfer), ["skipped"] * 4)
        self.assertEqual(
            transfer.steps[0]["detail"],
            "Skipped because this was a dry run.",
        )


class ConfirmViewTest(TestCase):
    def setUp(self):
        _sign_in(self.client)
        patcher = mock.patch("email_transfer_service.views.EtsClient.from_settings")
        self.from_settings = patcher.start()
        self.addCleanup(patcher.stop)

    def _confirm(self) -> HttpResponseBase:
        return self.client.post(
            reverse("ets:index"),
            {"old_email": OLD, "new_email": NEW, "confirm": "true"},
        )

    @override_settings(ETS_DRY_RUN=False)
    def test_confirm_runs_the_transfer_and_shows_it(self):
        client = _client()
        self.from_settings.return_value = client
        response = self._confirm()
        transfer = EmailTransfer.objects.get()
        self.assertRedirects(response, transfer.get_absolute_url())
        self.assertEqual(len(client.calls), 3)
        detail = self.client.get(transfer.get_absolute_url())
        self.assertContains(detail, transfer.slug)
        self.assertContains(detail, f"Turn off sign-in for {OLD}.")
        for word in TECHNICAL_WORDS:
            self.assertNotContains(detail, word)

    def test_preconditions_are_rechecked_on_confirm(self):
        # The new email gained an active record after the preview.
        client = _client(new_record_status="active")
        self.from_settings.return_value = client
        response = self._confirm()
        self.assertContains(response, "already has its own GCI/VCI profile")
        self.assertFalse(EmailTransfer.objects.exists())
        self.assertEqual(client.calls, [])

    @override_settings(ETS_DRY_RUN=True)
    def test_dry_run_setting_is_used(self):
        client = _client()
        self.from_settings.return_value = client
        self._confirm()
        self.assertTrue(EmailTransfer.objects.get().dry_run)
        self.assertEqual(client.calls, [])

    def test_history_records_who_ran_the_transfer(self):
        self.from_settings.return_value = _client()
        self._confirm()
        transfer = EmailTransfer.objects.get()
        self.assertEqual(transfer.ran_by.username, "staff@example.com")
        history = transfer.history.all()  # type: ignore
        self.assertEqual({record.history_user for record in history}, {transfer.ran_by})

    def test_list_shows_past_transfers(self):
        self.from_settings.return_value = _client()
        self._confirm()
        transfer = EmailTransfer.objects.get()
        response = self.client.get(reverse("ets:list"))
        self.assertContains(response, transfer.slug)
        self.assertContains(response, transfer.get_absolute_url())

    def test_list_and_detail_need_ets_permissions(self):
        transfer = EmailTransfer.objects.create(old_email=OLD, new_email=NEW)
        self.client.logout()
        self.client.force_login(User.objects.create_user(username="other@example.com"))
        for url in [reverse("ets:list"), transfer.get_absolute_url()]:
            self.assertEqual(self.client.get(url).status_code, 403)


class FailedTransferPageTest(TestCase):
    def test_detail_page_hides_the_raw_error(self):
        _sign_in(self.client)
        client = _client(fail_on="disable_cognito_user")
        transfer = run_transfer(client, _plan(client), ran_by=None, dry_run=False)
        response = self.client.get(transfer.get_absolute_url())
        self.assertNotContains(response, "disable_cognito_user failed")
        self.assertContains(response, "The transfer stopped partway.")


class TabsTest(TestCase):
    def test_each_page_has_the_header_and_the_right_tab_active(self):
        _sign_in(self.client)
        transfer = EmailTransfer.objects.create(old_email=OLD, new_email=NEW)
        pages = {
            reverse("ets:index"): "New Transfer",
            reverse("ets:list"): "Past Transfers",
            transfer.get_absolute_url(): "Past Transfers",
        }
        for url, active in pages.items():
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertContains(
                    response, '<h1 class="title">Email Transfer Service'
                )
                self.assertContains(response, escape(get_tool("ets").description))
                self.assertContains(response, '<div class="tabs is-boxed">')
                self.assertContains(response, 'aria-current="page"', count=1)
                html = response.content.decode()
                active_link = html.split('aria-current="page"')[1].split("</a>")[0]
                self.assertIn(active, active_link)
                self.assertNotContains(response, 'class="button is-link is-light"')
