"""Houses tests for the AS's home page and its place on the landing page."""

from django.test import TestCase
from django.urls import reverse

from affiliations_service.tests.helpers import FLAVOR_TEXT, make_staff


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
