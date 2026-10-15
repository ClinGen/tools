"""Houses tests for the auth_ app."""

from unittest.mock import MagicMock, patch

from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.views.generic import View

from auth_.backends import ClerkBackend
from auth_.models import UserProfile
from auth_.permissions import ToolPermissionMixin, tool_permission_required


def _make_user(username: str, *, ets: bool = False) -> User:
    """Returns a user whose profile has the given ETS permission."""
    user = User.objects.create_user(username=username, email=username)
    UserProfile.objects.create(user=user, has_ets_permissions=ets)
    return user


class _EtsView(ToolPermissionMixin, View):
    tool_permission = "has_ets_permissions"

    @staticmethod
    def get(_request: object, *_args: object, **_kwargs: object) -> HttpResponse:
        return HttpResponse("ok")


@tool_permission_required("has_ets_permissions")
def _ets_function_view(_request: HttpRequest) -> HttpResponse:
    return HttpResponse("ok")


class ToolPermissionTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.views = {
            "mixin": _EtsView.as_view(),
            "decorator": _ets_function_view,
        }

    def _request(self, user: User | None) -> HttpRequest:
        request = self.factory.get("/ets/")
        request.user = user or AnonymousUser()
        return request

    def test_anonymous_user_is_sent_to_sign_in(self):
        for kind, view in self.views.items():
            with self.subTest(kind=kind):
                response = view(self._request(None))
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response["Location"], f"{reverse('login')}?next=/ets/")

    def test_user_without_the_flag_gets_403(self):
        user = _make_user("no-ets@example.com")
        for kind, view in self.views.items():
            with self.subTest(kind=kind), self.assertRaises(PermissionDenied):
                view(self._request(user))

    def test_user_without_a_profile_gets_403(self):
        user = User.objects.create_user(username="no-profile@example.com")
        for kind, view in self.views.items():
            with self.subTest(kind=kind), self.assertRaises(PermissionDenied):
                view(self._request(user))

    def test_user_with_the_flag_gets_200(self):
        user = _make_user("ets@example.com", ets=True)
        for kind, view in self.views.items():
            with self.subTest(kind=kind):
                self.assertEqual(view(self._request(user)).status_code, 200)

    def test_unknown_flag_is_a_configuration_error(self):
        view = tool_permission_required("has_typo_permissions")(_ets_function_view)
        user = _make_user("typo@example.com", ets=True)
        with self.assertRaises(ImproperlyConfigured):
            view(self._request(user))


class GrantingPermissionTest(TestCase):
    def test_granting_a_flag_is_recorded_in_history(self):
        user = _make_user("grant@example.com")
        profile = user.profile  # type: ignore
        profile.has_ets_permissions = True
        profile.save()
        latest = profile.history.first()
        self.assertTrue(latest.has_ets_permissions)
        self.assertEqual(profile.history.count(), 2)


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
        old_user = _make_user("linked@example.com", ets=True)
        backend = ClerkBackend()
        user = backend.authenticate(
            None, clerk_user_id="user_clerk_123", clerk_email="linked@example.com"
        )
        assert user is not None
        self.assertEqual(user.pk, old_user.pk)
        profile = UserProfile.objects.get(user=old_user)
        self.assertEqual(profile.clerk_user_id, "user_clerk_123")
        self.assertTrue(profile.has_ets_permissions)


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
        self.client.force_login(_make_user("in@example.com"))
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
        user = _make_user("bye@example.com")
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
        self.client.force_login(_make_user("p@example.com", ets=True))
        response = self.client.get(reverse("profile"))
        self.assertContains(response, "ETS Permissions")
        self.assertContains(response, "You can use the Email Transfer Service.")


class LandingPageAuthTest(TestCase):
    def test_landing_page_is_public(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'href="{reverse("login")}"')

    def test_landing_page_offers_log_out_and_profile_when_signed_in(self):
        self.client.force_login(_make_user("me@example.com"))
        response = self.client.get(reverse("home"))
        self.assertContains(response, f'href="{reverse("logout")}"')
        self.assertContains(response, f'href="{reverse("profile")}"')
        self.assertNotContains(response, f'href="{reverse("login")}"')
