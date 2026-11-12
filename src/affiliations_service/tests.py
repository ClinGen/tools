"""Houses tests for the AS's pages."""

from django.contrib.auth.models import User as StaffUser
from django.test import TestCase
from django.urls import reverse

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


class IndexViewTest(TestCase):
    def test_anonymous_user_is_sent_to_sign_in(self):
        url = reverse("as:index")
        response = self.client.get(url)
        self.assertRedirects(
            response, f"{reverse('login')}?next={url}", fetch_redirect_response=False
        )

    def test_user_without_the_flag_gets_403(self):
        self.client.force_login(make_staff("no-as@example.com", as_=False))
        self.assertEqual(self.client.get(reverse("as:index")).status_code, 403)

    def test_user_with_the_flag_sees_the_as(self):
        self.client.force_login(make_staff("as@example.com"))
        response = self.client.get(reverse("as:index"))
        self.assertContains(response, "Affiliations Service")

    def test_the_header_shows_the_as_description(self):
        self.client.force_login(make_staff("desc@example.com"))
        response = self.client.get(reverse("as:index"))
        self.assertContains(response, FLAVOR_TEXT)

    def test_index_is_mounted_at_as(self):
        self.assertEqual(reverse("as:index"), "/as/")


class LandingPageTest(TestCase):
    def test_landing_page_describes_the_as(self):
        self.assertContains(self.client.get(reverse("home")), FLAVOR_TEXT)

    def test_landing_page_links_to_the_as(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, f'href="{reverse("as:index")}"')
