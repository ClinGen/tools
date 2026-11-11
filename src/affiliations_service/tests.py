"""Houses tests for the AS's pages."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from auth_.models import UserProfile


def make_user(username: str, *, as_: bool = True) -> User:
    """Returns a user whose profile has or lacks the AS permission.

    Args:
        username: The username and email of the new user.
        as_: Whether the user has `has_as_permissions`.

    Returns:
        The new user.
    """
    user = User.objects.create_user(username=username, email=username)
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
        self.client.force_login(make_user("no-as@example.com", as_=False))
        self.assertEqual(self.client.get(reverse("as:index")).status_code, 403)

    def test_user_with_the_flag_sees_the_as(self):
        self.client.force_login(make_user("as@example.com"))
        response = self.client.get(reverse("as:index"))
        self.assertContains(response, "Affiliations Service")

    def test_index_is_mounted_at_as(self):
        self.assertEqual(reverse("as:index"), "/as/")


class LandingPageTest(TestCase):
    def test_landing_page_links_to_the_as(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, f'href="{reverse("as:index")}"')
