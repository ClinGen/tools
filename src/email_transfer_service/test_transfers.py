from unittest import mock

from django.contrib.auth.models import User
from django.core.exceptions import ImproperlyConfigured
from django.test import TestCase, override_settings
from django.urls import reverse

from auth_.models import UserProfile
from email_transfer_service.clients import CognitoUser, UserRecord
from email_transfer_service.fakes import FakeEtsClient
from email_transfer_service.transfers import check_preconditions

OLD = "old@example.com"
NEW = "new@example.com"


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

    def test_any_other_new_record_status_fails(self):
        preview = check_preconditions(_client(new_record_status="active"), OLD, NEW)
        self.assertIsNone(preview.plan)
        self.assertEqual(len(preview.failures), 1)
        self.assertIn('user_status "active"', preview.failures[0])

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
                f"The old email ({OLD}) has no Cognito user.",
                f"The old email ({OLD}) has no DynamoDB user record.",
                f"The new email ({NEW}) has no Cognito user.",
            ],
        )

    def test_already_enabled_new_user_is_skipped(self):
        preview = check_preconditions(_client(new_enabled=True), OLD, NEW)
        enable = preview.plan.steps()[-1]  # type: ignore
        self.assertEqual(enable.name, "enable_new_user")
        self.assertEqual(enable.skip_reason, "The new user is already enabled.")

    def test_steps_name_the_users_and_records(self):
        preview = check_preconditions(_client(), OLD, NEW)
        descriptions = " ".join(
            step.description
            for step in preview.plan.steps()  # type: ignore
        )
        for name in ["old-pk", "old-user", "new-user", NEW]:
            self.assertIn(name, descriptions)


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
        self.assertContains(response, "has no DynamoDB user record")
        self.assertNotContains(response, "Confirm Transfer")

    def test_valid_preview_lists_the_steps(self):
        self.from_settings.return_value = _client(
            new_record_status="requested activation"
        )
        response = self.client.post(
            reverse("ets:index"),
            {"old_email": OLD, "new_email": NEW},
        )
        self.assertContains(response, "Retire the new email&#x27;s DynamoDB record")
        self.assertContains(response, "Disable Cognito user old-user")
        self.assertContains(response, "Confirm Transfer")

    def test_aws_errors_are_flashed(self):
        self.from_settings.side_effect = ImproperlyConfigured("no user pool")
        response = self.client.post(
            reverse("ets:index"),
            {"old_email": OLD, "new_email": NEW},
        )
        self.assertContains(response, "Couldn&#x27;t check the preconditions")
        self.assertNotContains(response, "Confirm Transfer")

    @override_settings(ETS_DRY_RUN=True)
    def test_dry_run_banner(self):
        response = self.client.get(reverse("ets:index"))
        self.assertContains(response, "Dry run")
