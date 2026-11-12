"""Houses helpers shared by the ETS's tests."""

from email_transfer_service.clients import CognitoUser, UserRecord
from email_transfer_service.tests.fakes import FakeEtsClient
from email_transfer_service.transfers import Plan, check_preconditions

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


def make_client(
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


def make_plan(client: FakeEtsClient) -> Plan:
    """Returns the plan for a transfer from OLD to NEW."""
    preview = check_preconditions(client, OLD, NEW)
    assert preview.plan
    return preview.plan
