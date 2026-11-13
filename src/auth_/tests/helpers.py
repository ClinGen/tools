"""Houses helpers shared by the auth_ app's tests."""

from django.contrib.auth.models import User

from auth_.models import UserProfile


def make_user(username: str, *, ets: bool = False, as_: bool = False) -> User:
    """Returns a user whose profile has the given ETS and AS permissions."""
    user = User.objects.create_user(username=username, email=username)
    UserProfile.objects.create(
        user=user, has_ets_permissions=ets, has_as_permissions=as_
    )
    return user
