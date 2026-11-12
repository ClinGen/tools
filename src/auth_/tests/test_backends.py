"""Houses tests for the Clerk authentication backend."""

from django.contrib.auth.models import User
from django.test import TestCase

from auth_.backends import ClerkBackend
from auth_.models import UserProfile
from auth_.tests.helpers import make_user


class ClerkBackendTest(TestCase):
    def test_returns_none_without_clerk_user_id(self):
        backend = ClerkBackend()
        result = backend.authenticate(None, clerk_email="test@example.com")
        self.assertIsNone(result)

    def test_new_user_created_when_no_match(self):
        backend = ClerkBackend()
        user = backend.authenticate(
            None, clerk_user_id="user_new", clerk_email="new@example.com"
        )
        assert user is not None
        self.assertEqual(user.username, "new@example.com")
        self.assertEqual(user.profile.clerk_user_id, "user_new")  # type: ignore
        self.assertFalse(user.profile.has_ets_permissions)  # type: ignore

    def test_existing_user_matched_by_clerk_id(self):
        existing = User.objects.create_user(username="existing@example.com")
        UserProfile.objects.create(user=existing, clerk_user_id="user_existing")
        backend = ClerkBackend()
        user = backend.authenticate(
            None, clerk_user_id="user_existing", clerk_email="existing@example.com"
        )
        assert user is not None
        self.assertEqual(user.pk, existing.pk)
        self.assertEqual(
            User.objects.filter(username="existing@example.com").count(), 1
        )

    def test_unlinked_user_matched_by_email_keeps_permissions(self):
        old_user = make_user("linked@example.com", ets=True)
        backend = ClerkBackend()
        user = backend.authenticate(
            None, clerk_user_id="user_clerk_123", clerk_email="linked@example.com"
        )
        assert user is not None
        self.assertEqual(user.pk, old_user.pk)
        profile = UserProfile.objects.get(user=old_user)
        self.assertEqual(profile.clerk_user_id, "user_clerk_123")
        self.assertTrue(profile.has_ets_permissions)
