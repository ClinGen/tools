"""Houses tests for the sign-in, sign-out, and profile pages."""

from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.urls import reverse

from auth_.tests.helpers import make_user


def _make_clerk_user(email: str) -> MagicMock:
    """Returns a mock Clerk user object with one primary email address."""
    email_obj = MagicMock()
    email_obj.id = "iea_primary"
    email_obj.email_address = email
    mock_user = MagicMock()
    mock_user.primary_email_address_id = "iea_primary"
    mock_user.email_addresses = [email_obj]
    return mock_user


class LoginViewTest(TestCase):
    def test_renders_the_sign_in_widget(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, 'id="clerk-sign-in"')

    def test_signed_in_user_is_sent_home(self):
        self.client.force_login(make_user("in@example.com"))
        response = self.client.get(reverse("login"))
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)


@patch("auth_.views.verify_token")
@patch("auth_.views.clerk")
class CallbackViewTest(TestCase):
    def _set_up_valid_token(
        self, mock_clerk: MagicMock, mock_verify: MagicMock
    ) -> None:
        mock_verify.return_value = {"sub": "user_abc", "sid": "sess_xyz"}
        mock_clerk.users.get.return_value = _make_clerk_user("hello@example.com")
        self.client.cookies["__session"] = "valid_token"

    def test_success_establishes_session(
        self, mock_clerk: MagicMock, mock_verify: MagicMock
    ):
        self._set_up_valid_token(mock_clerk, mock_verify)
        response = self.client.get(reverse("callback"))
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.session["clerk_session_id"], "sess_xyz")

    def test_missing_cookie_redirects_to_login(
        self, _mock_clerk: MagicMock, _mock_verify: MagicMock
    ):
        response = self.client.get(reverse("callback"))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)

    def test_invalid_token_redirects_to_login(
        self, _mock_clerk: MagicMock, mock_verify: MagicMock
    ):
        mock_verify.side_effect = Exception("bad token")
        self.client.cookies["__session"] = "garbage"
        with self.assertLogs("auth_.views", level="ERROR"):
            response = self.client.get(reverse("callback"))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)

    def test_no_primary_email_redirects_to_login(
        self, mock_clerk: MagicMock, mock_verify: MagicMock
    ):
        mock_verify.return_value = {"sub": "user_noemail", "sid": "sess_1"}
        no_email_user = MagicMock()
        no_email_user.primary_email_address_id = "iea_missing"
        no_email_user.email_addresses = []
        mock_clerk.users.get.return_value = no_email_user
        self.client.cookies["__session"] = "valid_token"
        with self.assertLogs("auth_.views", level="WARNING"):
            response = self.client.get(reverse("callback"))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)


@patch("auth_.views.clerk")
class LogoutViewTest(TestCase):
    def test_revokes_the_clerk_session_and_signs_out(self, mock_clerk: MagicMock):
        user = make_user("bye@example.com")
        self.client.force_login(user)
        session = self.client.session
        session["clerk_session_id"] = "sess_bye"
        session.save()
        response = self.client.get(reverse("logout"))
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        mock_clerk.sessions.revoke.assert_called_once_with(session_id="sess_bye")
        self.assertNotIn("_auth_user_id", self.client.session)


class ProfileViewTest(TestCase):
    def test_anonymous_user_is_sent_to_sign_in(self):
        response = self.client.get(reverse("profile"))
        self.assertRedirects(response, reverse("login"), fetch_redirect_response=False)

    def test_shows_whether_the_user_has_ets_permissions(self):
        self.client.force_login(make_user("p@example.com", ets=True))
        response = self.client.get(reverse("profile"))
        self.assertContains(response, "ETS Permissions")
        self.assertContains(response, "You can use the Email Transfer Service.")

    def test_shows_whether_the_user_has_css_permissions(self):
        user = make_user("c@example.com")
        user.profile.has_css_permissions = True  # type: ignore
        user.profile.save()  # type: ignore
        self.client.force_login(user)
        response = self.client.get(reverse("profile"))
        self.assertContains(response, "CSS Permissions")
        self.assertContains(response, "You can use the ClinVar Submission Service.")

    def test_shows_whether_the_user_has_as_permissions(self):
        self.client.force_login(make_user("as-yes@example.com", as_=True))
        response = self.client.get(reverse("profile"))
        self.assertContains(response, "AS Permissions")
        self.assertContains(response, "You can use the Affiliations Service.")

    def test_tells_users_without_as_permissions_whom_to_ask(self):
        self.client.force_login(make_user("as-no@example.com"))
        response = self.client.get(reverse("profile"))
        self.assertContains(
            response, "Ask an administrator to grant you AS permissions."
        )


class LandingPageAuthTest(TestCase):
    def test_landing_page_is_public(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("login")}"')

    def test_landing_page_offers_log_out_and_profile_when_signed_in(self):
        self.client.force_login(make_user("me@example.com"))
        response = self.client.get(reverse("home"))
        self.assertContains(response, f'href="{reverse("logout")}"')
        self.assertContains(response, f'href="{reverse("profile")}"')
        self.assertNotContains(response, f'href="{reverse("login")}"')
