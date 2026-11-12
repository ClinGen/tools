"""Houses tests for managing an affiliation's members from its page."""

from typing import TYPE_CHECKING

from django.test import TestCase
from django.urls import reverse

from affiliations_service.models import Membership
from affiliations_service.test_memberships import TODAY, make_membership
from affiliations_service.test_models import make_affiliation
from affiliations_service.test_people import make_person
from affiliations_service.tests import make_user

if TYPE_CHECKING:
    # Django's stubs name the test client's response type only for type checkers.
    from django.test.client import _MonkeyPatchedWSGIResponse as Response  # ruff: ignore[import-private-name]

HTMX = {"HX-Request": "true"}


class AddMemberTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.affiliation = make_affiliation(full_name="Cardiomyopathy VCEP")
        cls.ada = make_person("ada@example.org", name="Ada Lovelace")

    def setUp(self):
        self.client.force_login(make_user("as@example.com"))
        self.url = reverse("as:membership-add", kwargs={"pk": self.affiliation.pk})

    def _post(self, headers: dict | None = None, **fields: str) -> "Response":
        data = {
            "person": str(self.ada.pk),
            "role": "COORDINATOR",
            "start_date": "",
        } | fields
        return self.client.post(
            self.url, data, headers=HTMX if headers is None else headers
        )

    def test_adding_a_member_shows_them_under_their_role(self):
        response = self._post(start_date=TODAY.isoformat())
        membership = Membership.objects.get()
        self.assertEqual(membership.start_date, TODAY)
        self.assertTemplateUsed(response, "affiliations_service/partials/members.html")
        page = response.content.decode()
        coordinators = page.index("Coordinators")
        self.assertIn("Ada Lovelace", page[coordinators : page.index("Approvers")])

    def test_adding_a_duplicate_open_role_shows_an_error(self):
        make_membership(self.ada, self.affiliation, Membership.Role.COORDINATOR)
        response = self._post()
        self.assertContains(
            response, "This person already holds this role in this affiliation."
        )
        self.assertEqual(Membership.objects.count(), 1)

    def test_without_htmx_it_redirects_to_the_affiliation(self):
        response = self._post(headers={})
        self.assertRedirects(response, self.affiliation.get_absolute_url())

    def test_a_deleted_affiliation_cant_get_members(self):
        self.affiliation.delete()
        response = self._post()
        self.assertContains(response, "This affiliation has been deleted.")
        self.assertFalse(Membership.objects.exists())

    def test_the_affiliation_page_has_the_add_member_form(self):
        page = self.client.get(self.affiliation.get_absolute_url()).content.decode()
        self.assertIn(self.url, page)
        self.assertIn(reverse("as:person-search"), page)


class EndMembershipTest(TestCase):
    def setUp(self):
        self.client.force_login(make_user("as@example.com"))
        self.affiliation = make_affiliation()
        self.membership = make_membership(
            make_person(name="Ada Lovelace"), self.affiliation
        )
        self.url = reverse("as:membership-end", kwargs={"pk": self.membership.pk})

    def test_ending_a_membership_moves_it_to_past_members(self):
        response = self.client.post(self.url, headers=HTMX)
        self.membership.refresh_from_db()
        self.assertEqual(self.membership.end_date, TODAY)
        page = response.content.decode()
        self.assertIn("Ada Lovelace", page[page.index("Past Members") :])

    def test_ending_asks_in_the_confirm_modal(self):
        page = self.client.get(self.affiliation.get_absolute_url()).content.decode()
        self.assertIn('data-confirm="End Ada Lovelace', page)
        self.assertNotIn("hx-confirm", page)

    def test_get_doesnt_end_a_membership(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.membership.refresh_from_db()
        self.assertIsNone(self.membership.end_date)

    def test_the_affiliation_page_offers_to_end_each_membership(self):
        self.assertContains(
            self.client.get(self.affiliation.get_absolute_url()), self.url
        )


class PersonSearchTest(TestCase):
    def setUp(self):
        self.client.force_login(make_user("as@example.com"))

    def test_finds_people_by_name_and_email(self):
        make_person("ada@example.org", name="Ada Lovelace")
        make_person("grace@navy.mil", name="Grace Hopper")
        url = reverse("as:person-search")
        by_name = self.client.get(url, {"q": "lovelace"}).content.decode()
        by_email = self.client.get(url, {"q": "navy"}).content.decode()
        self.assertIn("Ada Lovelace", by_name)
        self.assertNotIn("Grace Hopper", by_name)
        self.assertIn("Grace Hopper", by_email)

    def test_offers_to_add_a_person_when_no_one_matches(self):
        response = self.client.get(reverse("as:person-search"), {"q": "nobody"})
        self.assertContains(response, reverse("as:person-create"))


class MemberPermissionTest(TestCase):
    def test_member_endpoints_require_the_as_permission(self):
        affiliation = make_affiliation()
        membership = make_membership(make_person(), affiliation)
        self.client.force_login(make_user("no-as@example.com", as_=False))
        for url in [
            reverse("as:membership-add", kwargs={"pk": affiliation.pk}),
            reverse("as:membership-end", kwargs={"pk": membership.pk}),
            reverse("as:person-search"),
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.client.post(url).status_code, 403)
