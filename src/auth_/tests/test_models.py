"""Houses tests for UserProfile."""

import uuid

from django.contrib.auth.models import User
from django.test import TestCase

from auth_.models import UserProfile
from auth_.tests.helpers import make_user


class GrantingPermissionTest(TestCase):
    def test_granting_a_flag_is_recorded_in_history(self):
        user = make_user("grant@example.com")
        profile = user.profile  # type: ignore
        profile.has_ets_permissions = True
        profile.save()
        latest = profile.history.first()
        self.assertTrue(latest.has_ets_permissions)
        self.assertEqual(profile.history.count(), 2)

    def test_granting_the_as_flag_is_recorded_in_history(self):
        user = make_user("grant-as@example.com")
        profile = user.profile  # type: ignore
        profile.has_as_permissions = True
        profile.save()
        self.assertTrue(profile.history.first().has_as_permissions)
        self.assertEqual(profile.history.count(), 2)


class UserProfileIdTest(TestCase):
    def test_profile_and_its_history_have_uuid_ids(self):
        user = User.objects.create_user(username="staff@example.com")
        profile = UserProfile.objects.create(user=user)
        self.assertIsInstance(profile.pk, uuid.UUID)
        self.assertIsInstance(profile.history.first().history_id, uuid.UUID)  # type: ignore
