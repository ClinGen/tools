"""Houses tests for the tool permission checks."""

from django.contrib.auth.models import AnonymousUser, User
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import HttpRequest, HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.views.generic import View

from auth_.permissions import ToolPermissionMixin, tool_permission_required
from auth_.tests.helpers import make_user


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
        user = make_user("no-ets@example.com")
        for kind, view in self.views.items():
            with self.subTest(kind=kind), self.assertRaises(PermissionDenied):
                view(self._request(user))

    def test_user_without_a_profile_gets_403(self):
        user = User.objects.create_user(username="no-profile@example.com")
        for kind, view in self.views.items():
            with self.subTest(kind=kind), self.assertRaises(PermissionDenied):
                view(self._request(user))

    def test_user_with_the_flag_gets_200(self):
        user = make_user("ets@example.com", ets=True)
        for kind, view in self.views.items():
            with self.subTest(kind=kind):
                self.assertEqual(view(self._request(user)).status_code, 200)

    def test_unknown_flag_is_a_configuration_error(self):
        view = tool_permission_required("has_typo_permissions")(_ets_function_view)
        user = make_user("typo@example.com", ets=True)
        with self.assertRaises(ImproperlyConfigured):
            view(self._request(user))


class AsPermissionTest(TestCase):
    """Checks that the AS's flag works with the permission helpers."""

    def setUp(self):
        self.factory = RequestFactory()

        class _AsView(ToolPermissionMixin, View):
            tool_permission = "has_as_permissions"

            @staticmethod
            def get(
                _request: object, *_args: object, **_kwargs: object
            ) -> HttpResponse:
                return HttpResponse("ok")

        @tool_permission_required("has_as_permissions")
        def _as_function_view(_request: HttpRequest) -> HttpResponse:
            return HttpResponse("ok")

        self.views = {"mixin": _AsView.as_view(), "decorator": _as_function_view}

    def _request(self, user: User) -> HttpRequest:
        request = self.factory.get("/as/")
        request.user = user
        return request

    def test_user_without_the_flag_gets_403(self):
        user = make_user("no-as@example.com", ets=True)
        for kind, view in self.views.items():
            with self.subTest(kind=kind), self.assertRaises(PermissionDenied):
                view(self._request(user))

    def test_user_with_the_flag_gets_200(self):
        user = make_user("as@example.com", as_=True)
        for kind, view in self.views.items():
            with self.subTest(kind=kind):
                self.assertEqual(view(self._request(user)).status_code, 200)
