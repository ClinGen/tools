"""Houses tests for the ETS's home page and its place on the landing page."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from auth_.models import UserProfile


def _make_user(username: str, *, ets: bool = False) -> User:
    """Returns a user whose profile has the given ETS permission."""
    user = User.objects.create_user(username=username, email=username)
    UserProfile.objects.create(user=user, has_ets_permissions=ets)
    return user


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
