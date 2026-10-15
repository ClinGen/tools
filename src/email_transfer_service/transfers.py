"""Checks a transfer's preconditions, plans its steps, and runs them.

`check_preconditions()` looks up both emails and returns a `Preview`: either every
failed precondition, or a `Plan` of the steps a transfer would run. `run_transfer()`
runs a plan's steps and records each one's result on an `EmailTransfer`. "The Email
Transfer Service" in `docs/design.md` lists the preconditions and the steps.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from django.contrib.auth.models import User

from email_transfer_service.clients import RETIRED_EMAIL, CognitoUser, UserRecord
from email_transfer_service.models import EmailTransfer

logger = logging.getLogger(__name__)

# The only user_status a new email's record may have; such a record is retired.
REQUESTED_ACTIVATION = "requested activation"


class Lookups(Protocol):
    """The lookups a preview needs, which `EtsClient` provides."""

    def find_cognito_user(self, email: str) -> CognitoUser | None:
        """Returns the Cognito user with the given email, or None."""
        ...

    def find_user_record(self, email: str) -> UserRecord | None:
        """Returns the DynamoDB user record with the given email, or None."""
        ...


class Writes(Lookups, Protocol):
    """The lookups and writes a transfer needs, which `EtsClient` provides."""

    def retire_record(self, pk: str) -> None:
        """Retires a user record."""
        ...

    def update_record_email(self, pk: str, email: str) -> None:
        """Sets a user record's email."""
        ...

    def disable_cognito_user(self, username: str) -> None:
        """Stops a Cognito user from signing in."""
        ...

    def enable_cognito_user(self, username: str) -> None:
        """Lets a Cognito user sign in."""
        ...


@dataclass(frozen=True)
class Step:
    """One change a transfer makes.

    Attributes:
        name: What the step does, such as "disable_old_user".
        summary: A plain sentence for staff that says what will change.
        description: A technical sentence for developers, naming the Cognito users
            and DynamoDB records.
        skip_reason: A plain sentence for staff that says why the step won't run, or
            "" if it will.
    """

    name: str
    summary: str
    description: str
    skip_reason: str = ""


@dataclass(frozen=True)
class Plan:
    """The users and records a transfer changes, found when it was previewed."""

    old_email: str
    new_email: str
    old_user: CognitoUser
    new_user: CognitoUser
    old_record: UserRecord
    new_record: UserRecord | None

    def steps(self) -> list[Step]:
        """Returns the transfer's steps, in the order they run."""
        steps = []
        if self.new_record:
            steps.append(
                Step(
                    name="retire_new_record",
                    summary=(
                        "Remove the empty GCI/VCI profile that was made for "
                        f"{self.new_email}."
                    ),
                    description=(
                        f"Retire the new email's DynamoDB record {self.new_record.pk}: "
                        f"set its email to {RETIRED_EMAIL}, its user_status to "
                        "inactive, and its status to deleted."
                    ),
                ),
            )
        steps += [
            Step(
                name="update_old_record",
                summary=(
                    f"Move the GCI/VCI profile from {self.old_email} to "
                    f"{self.new_email}, keeping the user's history."
                ),
                description=(
                    f"Set the email on DynamoDB record {self.old_record.pk} to "
                    f"{self.new_email}."
                ),
            ),
            Step(
                name="disable_old_user",
                summary=f"Turn off sign-in for {self.old_email}.",
                description=(
                    f"Disable Cognito user {self.old_user.username} ({self.old_email})."
                ),
            ),
            Step(
                name="enable_new_user",
                summary=f"Turn on sign-in for {self.new_email}.",
                description=(
                    f"Enable Cognito user {self.new_user.username} ({self.new_email})."
                ),
                skip_reason=(
                    "Sign-in is already on for this email."
                    if self.new_user.enabled
                    else ""
                ),
            ),
        ]
        return steps


@dataclass(frozen=True)
class Preview:
    """The result of checking a transfer's preconditions.

    Attributes:
        failures: Each precondition that failed, as a plain sentence for staff.
        plan: The transfer's plan, or None if any precondition failed.
    """

    failures: list[str] = field(default_factory=list)
    plan: Plan | None = None


def check_preconditions(client: Lookups, old_email: str, new_email: str) -> Preview:
    """Looks up both emails and checks that a transfer can run.

    Args:
        client: Finds Cognito users and DynamoDB user records.
        old_email: The email the account is moving from.
        new_email: The email the account is moving to.

    Returns:
        A preview with every failed precondition, or with the plan if none failed.
    """
    old_user = client.find_cognito_user(old_email)
    old_record = client.find_user_record(old_email)
    new_user = client.find_cognito_user(new_email)
    new_record = client.find_user_record(new_email)

    failures = []
    if not old_user:
        failures.append(f"{old_email} has no sign-in account.")
    if not old_record:
        failures.append(f"{old_email} has no GCI/VCI profile.")
    if not new_user:
        failures.append(
            f"{new_email} has no sign-in account. The user needs to sign in to the "
            "GCI or VCI with it once before the transfer.",
        )
    if new_record and new_record.user_status != REQUESTED_ACTIVATION:
        logger.info(
            f"Can't transfer {old_email} to {new_email}: the new email has DynamoDB "
            f"user record {new_record.pk} with user_status {new_record.user_status!r}.",
        )
        failures.append(
            f"{new_email} already has its own GCI/VCI profile, so the ETS can't move "
            "another one onto it. Ask a developer for help.",
        )
    if failures or not (old_user and old_record and new_user):
        return Preview(failures=failures)
    return Preview(
        plan=Plan(
            old_email=old_email,
            new_email=new_email,
            old_user=old_user,
            new_user=new_user,
            old_record=old_record,
            new_record=new_record,
        ),
    )


def _actions(client: Writes, plan: Plan) -> dict[str, Callable[[], None]]:
    """Returns the AWS write for each of a plan's steps, keyed by step name."""
    actions = {
        "update_old_record": lambda: client.update_record_email(
            plan.old_record.pk,
            plan.new_email,
        ),
        "disable_old_user": lambda: client.disable_cognito_user(plan.old_user.username),
        "enable_new_user": lambda: client.enable_cognito_user(plan.new_user.username),
    }
    if plan.new_record:
        new_record_pk = plan.new_record.pk
        actions["retire_new_record"] = lambda: client.retire_record(new_record_pk)
    return actions


def run_transfer(
    client: Writes,
    plan: Plan,
    *,
    ran_by: User | None,
    dry_run: bool,
) -> EmailTransfer:
    """Runs a plan's steps in order, recording each step's result as it finishes.

    The transfer is saved before the first step, so it exists even if the server
    stops partway. The run stops at the first failure and doesn't undo earlier steps.
    In a dry run, every step is recorded as skipped and nothing in AWS changes.

    Args:
        client: Makes the AWS writes.
        plan: The plan from a passing preview.
        ran_by: The staff member running the transfer.
        dry_run: Whether to skip the AWS writes.

    Returns:
        The saved transfer, which has succeeded or failed.
    """
    steps = plan.steps()
    transfer = EmailTransfer.objects.create(
        old_email=plan.old_email,
        new_email=plan.new_email,
        ran_by=ran_by,
        old_username=plan.old_user.username,
        new_username=plan.new_user.username,
        old_record_pk=plan.old_record.pk,
        retired_record_pk=plan.new_record.pk if plan.new_record else "",
        dry_run=dry_run,
        steps=[
            {
                "name": step.name,
                "summary": step.summary,
                "description": step.description,
                "result": "not run",
                "detail": "",
                "error": "",
            }
            for step in steps
        ],
    )
    actions = _actions(client, plan)
    for record, step in zip(transfer.steps, steps, strict=True):
        if step.skip_reason or dry_run:
            record["result"] = "skipped"
            record["detail"] = step.skip_reason or "Skipped because this was a dry run."
        else:
            try:
                actions[step.name]()
            except Exception as error:
                logger.exception(f"Transfer {transfer.slug} failed at {step.name}.")
                record["result"] = "failed"
                record["error"] = str(error)
                transfer.status = EmailTransfer.Status.FAILED
                transfer.error = str(error)
                transfer.save()
                return transfer
            record["result"] = "succeeded"
        transfer.save()
    transfer.status = EmailTransfer.Status.SUCCEEDED
    transfer.save()
    return transfer
