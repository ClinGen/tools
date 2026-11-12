"""Provides a fake EtsClient for tests, so they never reach AWS."""

from email_transfer_service.clients import CognitoUser, UserRecord


class FakeEtsClient:
    """Stands in for `EtsClient`, holding users and records in memory.

    Each write is appended to `calls`. Name a method in `fail_on` to make it raise.
    """

    def __init__(
        self,
        *,
        users: list[CognitoUser] | None = None,
        records: list[UserRecord] | None = None,
        fail_on: str = "",
    ) -> None:
        """Holds the given users and records.

        Args:
            users: The Cognito users to find by email.
            records: The DynamoDB user records to find by email.
            fail_on: The name of a write method that should raise.
        """
        self.users = {user.email: user for user in users or []}
        self.records = {record.email: record for record in records or []}
        self.fail_on = fail_on
        self.calls: list[tuple[str, ...]] = []

    def find_cognito_user(self, email: str) -> CognitoUser | None:
        """Returns the user with the given email, or None."""
        return self.users.get(email)

    def find_user_record(self, email: str) -> UserRecord | None:
        """Returns the record with the given email, or None."""
        return self.records.get(email)

    def _write(self, *call: str) -> None:
        if call[0] == self.fail_on:
            error_message = f"{call[0]} failed"
            raise RuntimeError(error_message)
        self.calls.append(call)

    def retire_record(self, pk: str) -> None:
        """Records a call to retire a record."""
        self._write("retire_record", pk)

    def update_record_email(self, pk: str, email: str) -> None:
        """Records a call to set a record's email."""
        self._write("update_record_email", pk, email)

    def disable_cognito_user(self, username: str) -> None:
        """Records a call to disable a user."""
        self._write("disable_cognito_user", username)

    def enable_cognito_user(self, username: str) -> None:
        """Records a call to enable a user."""
        self._write("enable_cognito_user", username)
