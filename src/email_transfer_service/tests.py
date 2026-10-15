import uuid
from unittest import mock

import boto3
from botocore.stub import Stubber
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from auth_.models import UserProfile
from email_transfer_service.clients import (
    CognitoUser,
    EtsClient,
    UserRecord,
)
from email_transfer_service.models import EmailTransfer

USER_POOL_ID = "us-west-2_test"
TABLE_NAME = "GeneVariantCuration-test"


def _make_user(username: str, *, ets: bool = False) -> User:
    """Returns a user whose profile has the given ETS permission."""
    user = User.objects.create_user(username=username, email=username)
    UserProfile.objects.create(user=user, has_ets_permissions=ets)
    return user


def _make_client() -> tuple[EtsClient, Stubber, Stubber]:
    """Returns an EtsClient whose AWS clients are stubbed, and the two stubbers."""
    session = boto3.Session(
        aws_access_key_id="test",
        aws_secret_access_key="test",  # ruff: ignore[hardcoded-password-func-arg]
        region_name="us-west-2",
    )
    cognito = session.client("cognito-idp")
    dynamodb = session.client("dynamodb")
    client = EtsClient(
        cognito=cognito,
        dynamodb=dynamodb,
        user_pool_id=USER_POOL_ID,
        table_name=TABLE_NAME,
    )
    return client, Stubber(cognito), Stubber(dynamodb)


def _cognito_user(username: str, email: str, *, enabled: bool = True) -> dict:
    """Returns a Cognito user as list_users returns it."""
    return {
        "Username": username,
        "Enabled": enabled,
        "Attributes": [{"Name": "email", "Value": email}],
    }


def _record(pk: str, email: str, user_status: str = "active") -> dict:
    """Returns a DynamoDB user record as query returns it."""
    return {
        "PK": {"S": pk},
        "email": {"S": email},
        "user_status": {"S": user_status},
    }


def _query_params(email: str, start_key: dict | None = None) -> dict:
    """Returns the parameters the client sends to find a record by email."""
    params = {
        "TableName": TABLE_NAME,
        "IndexName": "item_type_index",
        "KeyConditionExpression": "item_type = :item_type",
        "FilterExpression": "#email = :email",
        "ExpressionAttributeNames": {"#email": "email"},
        "ExpressionAttributeValues": {
            ":item_type": {"S": "user"},
            ":email": {"S": email},
        },
    }
    if start_key:
        params["ExclusiveStartKey"] = start_key
    return params


class FindCognitoUserTest(TestCase):
    def test_returns_the_user(self):
        client, cognito, _ = _make_client()
        cognito.add_response(
            "list_users",
            {"Users": [_cognito_user("abc-123", "old@example.com", enabled=False)]},
            {"UserPoolId": USER_POOL_ID, "Filter": 'email = "old@example.com"'},
        )
        with cognito:
            user = client.find_cognito_user("old@example.com")
        self.assertEqual(
            user,
            CognitoUser(username="abc-123", email="old@example.com", enabled=False),
        )

    def test_returns_none_when_not_found(self):
        client, cognito, _ = _make_client()
        cognito.add_response(
            "list_users",
            {"Users": []},
            {"UserPoolId": USER_POOL_ID, "Filter": 'email = "new@example.com"'},
        )
        with cognito:
            self.assertIsNone(client.find_cognito_user("new@example.com"))

    def test_rejects_an_email_that_would_break_the_filter(self):
        client, _, _ = _make_client()
        with self.assertRaises(ValueError):
            client.find_cognito_user('a"@example.com')


class FindUserRecordTest(TestCase):
    def test_returns_the_record(self):
        client, _, dynamodb = _make_client()
        dynamodb.add_response(
            "query",
            {"Items": [_record("pk-1", "old@example.com")]},
            _query_params("old@example.com"),
        )
        with dynamodb:
            record = client.find_user_record("old@example.com")
        self.assertEqual(
            record,
            UserRecord(pk="pk-1", email="old@example.com", user_status="active"),
        )

    def test_follows_pagination(self):
        client, _, dynamodb = _make_client()
        start_key = {"PK": {"S": "pk-0"}, "item_type": {"S": "user"}}
        dynamodb.add_response(
            "query",
            {"Items": [], "LastEvaluatedKey": start_key},
            _query_params("old@example.com"),
        )
        dynamodb.add_response(
            "query",
            {"Items": [_record("pk-1", "old@example.com", "requested activation")]},
            _query_params("old@example.com", start_key),
        )
        with dynamodb:
            record = client.find_user_record("old@example.com")
        self.assertEqual(record.user_status, "requested activation")  # type: ignore
        dynamodb.assert_no_pending_responses()

    def test_returns_none_when_not_found(self):
        client, _, dynamodb = _make_client()
        start_key = {"PK": {"S": "pk-0"}, "item_type": {"S": "user"}}
        dynamodb.add_response(
            "query",
            {"Items": [], "LastEvaluatedKey": start_key},
            _query_params("new@example.com"),
        )
        dynamodb.add_response(
            "query",
            {"Items": []},
            _query_params("new@example.com", start_key),
        )
        with dynamodb:
            self.assertIsNone(client.find_user_record("new@example.com"))


class WriteTest(TestCase):
    def test_retire_record(self):
        client, _, dynamodb = _make_client()
        dynamodb.add_response(
            "update_item",
            {},
            {
                "TableName": TABLE_NAME,
                "Key": {"PK": {"S": "pk-2"}},
                "UpdateExpression": (
                    "SET #email = :email, user_status = :user_status, #status = :status"
                ),
                "ExpressionAttributeNames": {"#email": "email", "#status": "status"},
                "ExpressionAttributeValues": {
                    ":email": {"S": "email.do.not.match"},
                    ":user_status": {"S": "inactive"},
                    ":status": {"S": "deleted"},
                },
            },
        )
        with dynamodb:
            client.retire_record("pk-2")
        dynamodb.assert_no_pending_responses()

    def test_update_record_email(self):
        client, _, dynamodb = _make_client()
        dynamodb.add_response(
            "update_item",
            {},
            {
                "TableName": TABLE_NAME,
                "Key": {"PK": {"S": "pk-1"}},
                "UpdateExpression": "SET #email = :email",
                "ExpressionAttributeNames": {"#email": "email"},
                "ExpressionAttributeValues": {":email": {"S": "new@example.com"}},
            },
        )
        with dynamodb:
            client.update_record_email("pk-1", "new@example.com")
        dynamodb.assert_no_pending_responses()

    def test_disable_and_enable_cognito_user(self):
        client, cognito, _ = _make_client()
        params = {"UserPoolId": USER_POOL_ID, "Username": "abc-123"}
        cognito.add_response("admin_disable_user", {}, params)
        cognito.add_response("admin_enable_user", {}, params)
        with cognito:
            client.disable_cognito_user("abc-123")
            client.enable_cognito_user("abc-123")
        cognito.assert_no_pending_responses()


class EmailTransferModelTest(TestCase):
    def _create(self) -> EmailTransfer:
        return EmailTransfer.objects.create(
            old_email="old@example.com",
            new_email="new@example.com",
        )

    def test_slug_is_t_and_the_start_of_the_uuid(self):
        transfer = self._create()
        self.assertIsInstance(transfer.pk, uuid.UUID)
        self.assertEqual(transfer.slug, f"T{transfer.pk.hex[:8]}")
        self.assertEqual(str(transfer), transfer.slug)

    def test_slug_does_not_change_on_later_saves(self):
        transfer = self._create()
        slug = transfer.slug
        transfer.status = EmailTransfer.Status.FAILED
        transfer.save()
        transfer.refresh_from_db()
        self.assertEqual(transfer.slug, slug)

    def test_colliding_slug_gets_a_new_uuid(self):
        taken = uuid.UUID("3f2a9c1e-0000-4000-8000-000000000001")
        fresh = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000002")
        EmailTransfer.objects.create(
            id=taken, old_email="a@example.com", new_email="b@example.com"
        )
        # Same first 8 hex characters as the taken one, so the slug collides.
        colliding = uuid.UUID("3f2a9c1e-ffff-4fff-8fff-ffffffffffff")
        with mock.patch("common.models.uuid.uuid4", return_value=fresh):
            transfer = EmailTransfer.objects.create(
                id=colliding,
                old_email="old@example.com",
                new_email="new@example.com",
            )
        self.assertEqual(transfer.pk, fresh)
        self.assertEqual(transfer.slug, "Taaaaaaaa")

    def test_changes_are_recorded_in_history(self):
        transfer = self._create()
        transfer.status = EmailTransfer.Status.SUCCEEDED
        transfer.save()
        self.assertEqual(transfer.history.first().status, "succeeded")  # type: ignore
        self.assertGreaterEqual(transfer.history.count(), 2)  # type: ignore


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
