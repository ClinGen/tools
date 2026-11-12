"""Houses tests for the ETS's home page and its place on the landing page."""

from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponseBase
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape

from auth_.models import UserProfile
from core.tools import get_tool
from email_transfer_service.models import EmailTransfer
from email_transfer_service.tests.helpers import (
    NEW,
    OLD,
    TECHNICAL_WORDS,
    make_client,
    make_plan,
)
from email_transfer_service.transfers import run_transfer


def _make_user(username: str, *, ets: bool = False) -> User:
    """Returns a user whose profile has the given ETS permission."""
    user = User.objects.create_user(username=username, email=username)
    UserProfile.objects.create(user=user, has_ets_permissions=ets)
    return user


class IndexViewTest(TestCase):
    def test_anonymous_user_is_sent_to_sign_in(self):
        response = self.client.get(reverse("ets:index"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/auth/login", response["Location"])

    def test_user_without_ets_permissions_gets_403(self):
        self.client.force_login(_make_user("staff@example.com"))
        response = self.client.get(reverse("ets:index"))
        self.assertEqual(response.status_code, 403)

    def test_user_with_ets_permissions_gets_200(self):
        self.client.force_login(_make_user("staff@example.com", ets=True))
        response = self.client.get(reverse("ets:index"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "email_transfer_service/index.html")
        self.assertContains(
            response,
            "Moves a GCI/VCI user&#x27;s account from an old email to a new one.",
        )

    def test_landing_page_lists_the_ets(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Email Transfer Service")
        self.assertContains(response, reverse("ets:index"))


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
        self.from_settings.return_value = make_client(old_record=False)
        response = self.client.post(
            reverse("ets:index"),
            {"old_email": OLD, "new_email": NEW},
        )
        self.assertContains(response, "has no GCI/VCI profile")
        self.assertNotContains(response, "Confirm Transfer")

    def test_valid_preview_lists_the_steps(self):
        self.from_settings.return_value = make_client(
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
        client = make_client()
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
        client = make_client(new_record_status="active")
        self.from_settings.return_value = client
        response = self._confirm()
        self.assertContains(response, "already has its own GCI/VCI profile")
        self.assertFalse(EmailTransfer.objects.exists())
        self.assertEqual(client.calls, [])

    @override_settings(ETS_DRY_RUN=True)
    def test_dry_run_setting_is_used(self):
        client = make_client()
        self.from_settings.return_value = client
        self._confirm()
        self.assertTrue(EmailTransfer.objects.get().dry_run)
        self.assertEqual(client.calls, [])

    def test_history_records_who_ran_the_transfer(self):
        self.from_settings.return_value = make_client()
        self._confirm()
        transfer = EmailTransfer.objects.get()
        self.assertEqual(transfer.ran_by.username, "staff@example.com")
        history = transfer.history.all()  # type: ignore
        self.assertEqual({record.history_user for record in history}, {transfer.ran_by})

    def test_list_shows_past_transfers(self):
        self.from_settings.return_value = make_client()
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
        client = make_client(fail_on="disable_cognito_user")
        transfer = run_transfer(client, make_plan(client), ran_by=None, dry_run=False)
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
            transfer.get_absolute_url(): f"Transfer {transfer.slug}",
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
                main = html.split("<main>")[1].split("</main>")[0]
                self.assertNotIn('class="button is-link is-light"', main)

    def test_only_the_detail_page_has_a_transfer_tab(self):
        _sign_in(self.client)
        transfer = EmailTransfer.objects.create(old_email=OLD, new_email=NEW)
        for url in [reverse("ets:index"), reverse("ets:list")]:
            self.assertNotContains(self.client.get(url), f"Transfer {transfer.slug}")


def _sign_in(client: object) -> None:
    user = User.objects.create_user(username="staff@example.com")
    UserProfile.objects.create(user=user, has_ets_permissions=True)
    client.force_login(user)  # type: ignore
