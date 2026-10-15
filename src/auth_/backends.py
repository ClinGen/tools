"""Provides a custom Clerk authentication backend."""

import logging
from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.http import HttpRequest

from auth_.models import UserProfile

logger = logging.getLogger(__name__)


class ClerkBackend(ModelBackend):
    """Enables authentication via Clerk."""

    def authenticate(
        self,
        request: HttpRequest | None,  # ruff: ignore[unused-method-argument]
        username: str | None = None,  # ruff: ignore[unused-method-argument]
        password: str | None = None,  # ruff: ignore[unused-method-argument]
        **kwargs: Any,  # ruff: ignore[any-type] (Matches the signature of the base class.)
    ) -> User | None:
        """Authenticates the user using a Clerk user ID and email address.

        Lookup proceeds in three stages:
          1. Match an existing UserProfile by clerk_user_id.
          2. Match an existing User by email (WorkOS migration path), then
             write clerk_user_id into the profile.
          3. Create a new User and UserProfile, setting clerk_user_id.

        Args:
            request: The HttpRequest object.
            username: Ignored; present to satisfy the base class signature.
            password: Ignored; present to satisfy the base class signature.
            kwargs: Must include clerk_user_id; optionally clerk_email.

        Returns:
            The authenticated User, or None if clerk_user_id is absent.
        """
        clerk_user_id = kwargs.get("clerk_user_id")
        clerk_email = kwargs.get("clerk_email")
        if not clerk_user_id:
            return None

        # Stage 1: Existing account already linked to this Clerk ID.
        try:
            profile = UserProfile.objects.get(clerk_user_id=clerk_user_id)
        except UserProfile.DoesNotExist:
            pass
        else:
            return profile.user

        # Stage 2: WorkOS migration path. Match by email, then store Clerk ID.
        if clerk_email:
            try:
                user = User.objects.get(username=clerk_email)
            except User.DoesNotExist:
                pass
            else:
                profile, _ = UserProfile.objects.get_or_create(user=user)
                profile.clerk_user_id = clerk_user_id
                profile.save()
                logger.info(f"Migrated user {clerk_email} to Clerk ID {clerk_user_id}")
                return user

        # Stage 3: No match found. Create a new user and profile.
        user, created = User.objects.get_or_create(
            username=clerk_email,
            defaults={"email": clerk_email or ""},
        )
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.clerk_user_id = clerk_user_id
        profile.save()
        if created:
            logger.info(f"Created new user for Clerk ID {clerk_user_id}")
        return user

    def get_user(self, user_id: int) -> User | None:
        """Returns a user based on the provided user_id."""
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            logger.warning(f"User with user ID {user_id} does not exist")
            return None
