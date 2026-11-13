"""Houses tests for the Sentry tool-tag middleware."""

from unittest.mock import MagicMock, patch

from django.http import HttpRequest, HttpResponse
from django.test import TestCase, override_settings
from django.urls import include, path

from config import urls as project_urls


def fake_ets_index(request: HttpRequest) -> HttpResponse:  # ruff: ignore[unused-function-argument]
    """Stands in for the ETS's index view.

    Returns:
        A response with the text "ETS".
    """
    return HttpResponse("ETS")


urlpatterns = [
    *project_urls.urlpatterns,
    path("ets/", include(([path("", fake_ets_index, name="index")], "ets"))),
]


@override_settings(ROOT_URLCONF="common.tests.test_middleware")
@patch("common.middleware.sentry_sdk.set_tag")
class ToolTagMiddlewareTest(TestCase):
    def test_tags_a_tool_request_with_the_tool(self, mock_set_tag: MagicMock):
        self.client.get("/ets/")
        mock_set_tag.assert_called_once_with("tool", "ets")

    def test_leaves_the_landing_page_untagged(self, mock_set_tag: MagicMock):
        self.client.get("/")
        mock_set_tag.assert_not_called()

    def test_leaves_sign_in_untagged(self, mock_set_tag: MagicMock):
        self.client.get("/auth/login")
        mock_set_tag.assert_not_called()
