"""Talks to the GCI and VCI user pool in Cognito and user records in DynamoDB.

Each method makes one of the AWS calls a transfer needs. `EtsClient.from_settings()`
builds a client from the ETS_ settings; tests build one around stubbed boto3 clients.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Self

import boto3
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

if TYPE_CHECKING:
    from mypy_boto3_cognito_idp import CognitoIdentityProviderClient
    from mypy_boto3_dynamodb import DynamoDBClient

# The GCI and VCI table's names for the things a transfer reads and writes.
PK_ATTRIBUTE = "PK"
EMAIL_ATTRIBUTE = "email"
ITEM_TYPE_INDEX = "item_type_index"

# A retired record's email, chosen so no real email matches it.
RETIRED_EMAIL = "email.do.not.match"


@dataclass(frozen=True)
class CognitoUser:
    """A user in the Cognito user pool.

    Attributes:
        username: Cognito's internal username, which the admin calls take.
        email: The user's email.
        enabled: Whether the user can sign in.
    """

    username: str
    email: str
    enabled: bool


@dataclass(frozen=True)
class UserRecord:
    """A user record in the DynamoDB table.

    Attributes:
        pk: The record's partition key.
        email: The record's email.
        user_status: The record's user_status, such as "active" or
            "requested activation".
    """

    pk: str
    email: str
    user_status: str


def _string(item: dict[str, Any], name: str) -> str:
    """Returns a string attribute of a DynamoDB item, or "" if it has none."""
    return item.get(name, {}).get("S", "")


class EtsClient:
    """Makes the Cognito and DynamoDB calls a transfer needs."""

    def __init__(
        self,
        *,
        cognito: "CognitoIdentityProviderClient",
        dynamodb: "DynamoDBClient",
        user_pool_id: str,
        table_name: str,
    ) -> None:
        """Wraps the given boto3 clients.

        Args:
            cognito: A boto3 cognito-idp client.
            dynamodb: A boto3 dynamodb client.
            user_pool_id: The ID of the GCI and VCI user pool.
            table_name: The name of the GCI and VCI table.
        """
        self.cognito = cognito
        self.dynamodb = dynamodb
        self.user_pool_id = user_pool_id
        self.table_name = table_name

    @classmethod
    def from_settings(cls) -> Self:
        """Returns a client configured by the ETS_ settings.

        Raises:
            ImproperlyConfigured: If the region, user pool ID, or table name is empty.
        """
        missing = [
            name
            for name in [
                "ETS_AWS_REGION",
                "ETS_COGNITO_USER_POOL_ID",
                "ETS_DYNAMODB_TABLE_NAME",
            ]
            if not getattr(settings, name)
        ]
        if missing:
            error_message = f"The ETS needs these settings: {', '.join(missing)}."
            raise ImproperlyConfigured(error_message)
        session = boto3.Session(
            aws_access_key_id=settings.ETS_AWS_ACCESS_KEY_ID or None,
            aws_secret_access_key=settings.ETS_AWS_SECRET_ACCESS_KEY or None,
            region_name=settings.ETS_AWS_REGION,
        )
        return cls(
            cognito=session.client("cognito-idp"),
            dynamodb=session.client("dynamodb"),
            user_pool_id=settings.ETS_COGNITO_USER_POOL_ID,
            table_name=settings.ETS_DYNAMODB_TABLE_NAME,
        )

    def find_cognito_user(self, email: str) -> CognitoUser | None:
        """Returns the Cognito user with the given email, or None.

        Raises:
            ValueError: If the email contains a character that would break Cognito's
                filter syntax.
        """
        if '"' in email or "\\" in email:
            error_message = (
                f"Can't look up an email with quotes or backslashes: {email}"
            )
            raise ValueError(error_message)
        response = self.cognito.list_users(
            UserPoolId=self.user_pool_id,
            Filter=f'email = "{email}"',
        )
        users = response.get("Users", [])
        if not users:
            return None
        user = users[0]
        attributes = {
            attribute["Name"]: attribute.get("Value", "")
            for attribute in user.get("Attributes", [])
        }
        return CognitoUser(
            username=user.get("Username", ""),
            email=attributes.get("email", ""),
            enabled=user.get("Enabled", False),
        )

    def find_user_record(self, email: str) -> UserRecord | None:
        """Returns the DynamoDB user record with the given email, or None.

        The email isn't a key, so this queries every user record and follows the pages
        until one matches.
        """
        params: dict[str, Any] = {
            "TableName": self.table_name,
            "IndexName": ITEM_TYPE_INDEX,
            "KeyConditionExpression": "item_type = :item_type",
            "FilterExpression": "#email = :email",
            "ExpressionAttributeNames": {"#email": EMAIL_ATTRIBUTE},
            "ExpressionAttributeValues": {
                ":item_type": {"S": "user"},
                ":email": {"S": email},
            },
        }
        while True:
            response = self.dynamodb.query(**params)
            items = response.get("Items", [])
            if items:
                item = items[0]
                return UserRecord(
                    pk=_string(item, PK_ATTRIBUTE),
                    email=_string(item, EMAIL_ATTRIBUTE),
                    user_status=_string(item, "user_status"),
                )
            last_key = response.get("LastEvaluatedKey")
            if not last_key:
                return None
            params["ExclusiveStartKey"] = last_key

    def retire_record(self, pk: str) -> None:
        """Retires a user record so no email matches it and it reads as deleted."""
        self.dynamodb.update_item(
            TableName=self.table_name,
            Key={PK_ATTRIBUTE: {"S": pk}},
            UpdateExpression=(
                "SET #email = :email, user_status = :user_status, #status = :status"
            ),
            ExpressionAttributeNames={"#email": EMAIL_ATTRIBUTE, "#status": "status"},
            ExpressionAttributeValues={
                ":email": {"S": RETIRED_EMAIL},
                ":user_status": {"S": "inactive"},
                ":status": {"S": "deleted"},
            },
        )

    def update_record_email(self, pk: str, email: str) -> None:
        """Sets a user record's email."""
        self.dynamodb.update_item(
            TableName=self.table_name,
            Key={PK_ATTRIBUTE: {"S": pk}},
            UpdateExpression="SET #email = :email",
            ExpressionAttributeNames={"#email": EMAIL_ATTRIBUTE},
            ExpressionAttributeValues={":email": {"S": email}},
        )

    def disable_cognito_user(self, username: str) -> None:
        """Stops a Cognito user from signing in."""
        self.cognito.admin_disable_user(UserPoolId=self.user_pool_id, Username=username)

    def enable_cognito_user(self, username: str) -> None:
        """Lets a Cognito user sign in."""
        self.cognito.admin_enable_user(UserPoolId=self.user_pool_id, Username=username)
