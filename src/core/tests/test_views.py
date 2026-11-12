"""Houses tests for the landing page and the error pages."""

from django.contrib.auth.models import User
from django.http import HttpRequest, HttpResponse
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import include, path, reverse
from django.views.defaults import server_error

from auth_.models import UserProfile
from config import urls as project_urls
from core.tools import TOOLS


def fake_ets_index(request: HttpRequest) -> HttpResponse:  # ruff: ignore[unused-function-argument]
    """Stands in for the ETS's index view.

    Returns:
        A response with the text "ETS".
    """
    return HttpResponse("ETS")


# The project's URLconf without its tools, so the tests don't depend on which real tools
# are mounted.
shared_urlpatterns = [
    pattern
    for pattern in project_urls.urlpatterns
    if getattr(pattern, "namespace", None) not in {tool.namespace for tool in TOOLS}
]


# The shared URLconf with a fake ETS mounted.
urlpatterns = [
    *shared_urlpatterns,
    path("ets/", include(([path("", fake_ets_index, name="index")], "ets"))),
]


class NoToolsUrlconf:
    """The shared URLconf with no tools mounted."""

    urlpatterns = shared_urlpatterns


def sign_in(client: Client, *, ets: bool) -> None:
    """Signs a user in, with or without ETS permissions."""
    user = User.objects.create_user(username="u@example.com", email="u@example.com")
    UserProfile.objects.create(user=user, has_ets_permissions=ets)
    client.force_login(user)


class HomeViewTest(TestCase):
    def test_renders_the_landing_page_in_the_base_layout(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "core/home.html")
        self.assertTemplateUsed(response, "layouts/base.html")
        self.assertContains(response, "<title>ClinGen Tools | Home</title>", html=True)

    @override_settings(ROOT_URLCONF=NoToolsUrlconf)
    def test_says_so_when_no_tools_are_mounted(self):
        response = self.client.get(reverse("home"))
        self.assertContains(response, "No tools are available yet.")
        for tool in TOOLS:
            self.assertNotContains(response, tool.name)

    @override_settings(ROOT_URLCONF="core.tests.test_views")
    def test_lists_a_mounted_tool_with_its_url(self):
        sign_in(self.client, ets=True)
        response = self.client.get(reverse("home"))
        self.assertContains(response, f'href="{reverse("ets:index")}"')
        self.assertContains(response, "Email Transfer Service (ETS)")
        self.assertNotContains(response, "No tools are available yet.")

    @override_settings(ROOT_URLCONF="core.tests.test_views")
    def test_leaves_out_unmounted_tools(self):
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "Affiliations Service")
        self.assertNotContains(response, "ClinVar Submission Service")

    def test_shows_the_ets_to_a_user_with_ets_permissions(self):
        sign_in(self.client, ets=True)
        response = self.client.get(reverse("home"))
        self.assertContains(response, "Email Transfer Service (ETS)")

    def test_hides_the_ets_from_a_user_without_ets_permissions(self):
        sign_in(self.client, ets=False)
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "Email Transfer Service")
        self.assertNotContains(response, f'href="{reverse("ets:index")}"')

    def test_hides_the_ets_from_anonymous_users(self):
        response = self.client.get(reverse("home"))
        self.assertNotContains(response, "Email Transfer Service")

    def test_shows_the_as_and_the_css_to_everyone(self):
        for ets in (None, False, True):
            with self.subTest(ets=ets):
                self.client.logout()
                User.objects.all().delete()
                if ets is not None:
                    sign_in(self.client, ets=ets)
                response = self.client.get(reverse("home"))
                self.assertContains(response, "Affiliations Service (AS)")
                self.assertContains(response, "ClinVar Submission Service (CSS)")


@override_settings(DEBUG=False)
class ErrorPageTest(TestCase):
    def test_404_renders_its_template(self):
        response = self.client.get("/this-page-does-not-exist/")
        self.assertEqual(response.status_code, 404)
        self.assertTemplateUsed(response, "404.html")
        self.assertContains(response, "404 Not Found", status_code=404)

    def test_500_renders_its_template(self):
        response = server_error(RequestFactory().get("/"))
        self.assertEqual(response.status_code, 500)
        self.assertIn(b"500 Internal Server Error", response.content)
