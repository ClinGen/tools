from django.contrib.auth.models import User
from django.test import TestCase

from email_transfer_service.models import EmailTransfer
from email_transfer_service.tests.helpers import (
    NEW,
    OLD,
    TECHNICAL_WORDS,
    make_client,
    make_plan,
)
from email_transfer_service.transfers import check_preconditions, run_transfer


class CheckPreconditionsTest(TestCase):
    def test_plan_without_a_new_record(self):
        preview = check_preconditions(make_client(), OLD, NEW)
        self.assertEqual(preview.failures, [])
        self.assertEqual(
            [step.name for step in preview.plan.steps()],  # type: ignore
            ["update_old_record", "disable_old_user", "enable_new_user"],
        )

    def test_plan_retires_a_requested_activation_record(self):
        preview = check_preconditions(
            make_client(new_record_status="requested activation"),
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
        preview = check_preconditions(make_client(new_record_status="active"), OLD, NEW)
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
            make_client(old_user=False, new_user=False, old_record=False),
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
        preview = check_preconditions(make_client(new_enabled=True), OLD, NEW)
        enable = preview.plan.steps()[-1]  # type: ignore
        self.assertEqual(enable.name, "enable_new_user")
        self.assertEqual(enable.skip_reason, "Sign-in is already on for this email.")

    def test_descriptions_name_the_users_and_records(self):
        preview = check_preconditions(
            make_client(new_record_status="requested activation"),
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
            make_client(new_record_status="requested activation", new_enabled=True),
            OLD,
            NEW,
        ).plan
        failures = check_preconditions(
            make_client(old_user=False, new_user=False, new_record_status="active"),
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


class RunTransferTest(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user(username="staff@example.com")

    def _results(self, transfer: EmailTransfer) -> list[str]:
        return [step["result"] for step in transfer.steps]

    def test_full_success(self):
        client = make_client()
        transfer = run_transfer(
            client, make_plan(client), ran_by=self.staff, dry_run=False
        )
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
        client = make_client(new_record_status="requested activation")
        transfer = run_transfer(
            client, make_plan(client), ran_by=self.staff, dry_run=False
        )
        self.assertEqual(client.calls[0], ("retire_record", "new-pk"))
        self.assertEqual(transfer.retired_record_pk, "new-pk")
        self.assertEqual(self._results(transfer), ["succeeded"] * 4)

    def test_already_enabled_new_user_is_skipped(self):
        client = make_client(new_enabled=True)
        transfer = run_transfer(
            client, make_plan(client), ran_by=self.staff, dry_run=False
        )
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
                client = make_client(
                    new_record_status="requested activation",
                    fail_on=write,
                )
                transfer = run_transfer(
                    client,
                    make_plan(client),
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
        client = make_client(new_record_status="requested activation")
        transfer = run_transfer(
            client, make_plan(client), ran_by=self.staff, dry_run=True
        )
        self.assertEqual(client.calls, [])
        self.assertTrue(transfer.dry_run)
        self.assertEqual(transfer.status, EmailTransfer.Status.SUCCEEDED)
        self.assertEqual(self._results(transfer), ["skipped"] * 4)
        self.assertEqual(
            transfer.steps[0]["detail"],
            "Skipped because this was a dry run.",
        )
