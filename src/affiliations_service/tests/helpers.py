"""Houses helpers shared by the AS's tests."""

from django.contrib.auth.models import User as StaffUser

from auth_.models import UserProfile

FLAVOR_TEXT = (
    "The source of truth for ClinGen and non-ClinGen users and groups working in "
    "ClinGen apps."
)


def make_staff(username: str, *, as_: bool = True) -> StaffUser:
    """Returns a user whose profile has or lacks the AS permission.

    Args:
        username: The username and email of the new user.
        as_: Whether the user has `has_as_permissions`.

    Returns:
        The new user.
    """
    user = StaffUser.objects.create_user(username=username, email=username)
    UserProfile.objects.create(user=user, has_as_permissions=as_)
    return user
