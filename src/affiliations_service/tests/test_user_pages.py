"""Houses tests for the users pages."""

from typing import TYPE_CHECKING

from django.test import TestCase
from django.urls import reverse

from affiliations_service.models import Membership, User, UserEmail
from affiliations_service.tests.helpers import make_staff
from affiliations_service.tests.test_memberships import YESTERDAY, make_membership
from affiliations_service.tests.test_models import make_affiliation
from affiliations_service.tests.test_users import make_user

if TYPE_CHECKING:
    # Django's stubs name the test client's response type only for type checkers.
    from django.test.client import _MonkeyPatchedWSGIResponse as Response  # ruff: ignore[import-private-name]


def emails_formset(*emails: str, existing: tuple[UserEmail, ...] = ()) -> dict:
    """Returns POST data for the other-emails formset."""
    prefix = "other_emails"
    rows = [(str(item.pk), item.email) for item in existing]
    rows += [("", email) for email in emails]
    data = {
        f"{prefix}-TOTAL_FORMS": str(len(rows)),
        f"{prefix}-INITIAL_FORMS": str(len(existing)),
        f"{prefix}-MIN_NUM_FORMS": "0",
        f"{prefix}-MAX_NUM_FORMS": "1000",
    }
    for index, (pk, email) in enumerate(rows):
        data[f"{prefix}-{index}-id"] = pk
        data[f"{prefix}-{index}-email"] = email
    return data


class UserListPageTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.ada = make_user("ada@example.org", name="Ada Lovelace")
        UserEmail.objects.create(user=cls.ada, email="countess@uni.edu")
        cls.grace = make_user("grace@example.org", name="Grace Hopper")

    def setUp(self):
        self.client.force_login(make_staff("as@example.com"))

    def _page(self, **params: str) -> str:
        return self.client.get(reverse("as:users"), params).content.decode()

    def test_lists_users_and_links_to_them(self):
        page = self._page()
        self.assertIn("Ada Lovelace", page)
        self.assertIn(self.grace.get_absolute_url(), page)

    def test_search_finds_users_by_name_and_other_email(self):
        self.assertNotIn("Ada Lovelace", self._page(q="hopper"))
        page = self._page(q="countess")
        self.assertIn("Ada Lovelace", page)
        self.assertNotIn("Grace Hopper", page)

    def test_the_tabs_link_to_the_users_list(self):
        self.assertContains(self.client.get(reverse("as:index")), reverse("as:users"))


class UserDetailPageTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.ada = make_user(
            "ada@example.org", name="Ada Lovelace", orcid="0000-0002-1825-0097"
        )
        UserEmail.objects.create(user=cls.ada, email="countess@uni.edu")
        cls.vcep = make_affiliation(full_name="Cardiomyopathy VCEP")
        cls.gcep = make_affiliation(full_name="Kidney GCEP")
        make_membership(cls.ada, cls.vcep, Membership.Role.COORDINATOR)
        make_membership(cls.ada, cls.gcep, Membership.Role.CURATOR, end_date=YESTERDAY)

    def setUp(self):
        self.client.force_login(make_staff("as@example.com"))

    def test_shows_fields_memberships_and_history(self):
        page = self.client.get(self.ada.get_absolute_url()).content.decode()
        current_start = page.index("Current Affiliations")
        past_start = page.index("Past Affiliations")
        for text in ["countess@uni.edu", "0000-0002-1825-0097", "Added the user."]:
            with self.subTest(text=text):
                self.assertIn(text, page)
        self.assertIn("Cardiomyopathy VCEP", page[current_start:past_start])
        self.assertIn(self.vcep.get_absolute_url(), page)
        self.assertIn("Kidney GCEP", page[past_start:])
        self.assertNotIn(
            str(self.ada.pk), page.replace(self.ada.get_absolute_url(), "")
        )

    def test_the_affiliation_page_links_to_its_members(self):
        page = self.client.get(self.vcep.get_absolute_url()).content.decode()
        self.assertIn(self.ada.get_absolute_url(), page)


class UserFormPageTest(TestCase):
    def setUp(self):
        self.client.force_login(make_staff("as@example.com"))

    def _fields(self, **fields: str) -> dict:
        return {
            "name": "Ada Lovelace",
            "preferred_name": "",
            "email": "ada@example.org",
            "institution": "",
            "orcid": "",
            "credentials": "",
            "gpm_uuid": "",
        } | fields

    def test_create_with_other_emails(self):
        response = self.client.post(
            reverse("as:user-create"), self._fields() | emails_formset("ada@uni.edu")
        )
        ada = User.objects.get()
        self.assertRedirects(response, ada.get_absolute_url())
        self.assertEqual([e.email for e in ada.other_emails.all()], ["ada@uni.edu"])  # type: ignore

    def test_create_without_an_email(self):
        response = self.client.post(
            reverse("as:user-create"), self._fields(email="") | emails_formset()
        )
        user = User.objects.get()
        self.assertRedirects(response, user.get_absolute_url())

    def test_edit_adds_and_removes_other_emails(self):
        ada = make_user()
        old = UserEmail.objects.create(user=ada, email="old@uni.edu")
        formset = emails_formset("new@uni.edu", existing=(old,))
        formset["other_emails-0-DELETE"] = "on"
        url = reverse("as:user-edit", kwargs={"pk": ada.pk})
        response = self.client.post(url, self._fields(institution="Stanford") | formset)
        self.assertRedirects(response, ada.get_absolute_url())
        ada.refresh_from_db()
        self.assertEqual(ada.institution, "Stanford")
        self.assertEqual([e.email for e in ada.other_emails.all()], ["new@uni.edu"])  # type: ignore

    def test_duplicate_emails_show_form_errors(self):
        grace = make_user("grace@example.org", name="Grace Hopper")
        UserEmail.objects.create(user=grace, email="grace@uni.edu")
        cases = [
            self._fields(email="GRACE@example.org") | emails_formset(),
            self._fields() | emails_formset("Grace@Uni.edu"),
            self._fields() | emails_formset("ada@example.org"),
        ]
        for data in cases:
            with self.subTest(data=data):
                response = self.client.post(reverse("as:user-create"), data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(
                    "already has this email." in response.content.decode()
                    or "This is already the user&#x27;s main email."
                    in response.content.decode()
                )
        self.assertEqual(User.objects.count(), 1)

    def test_bad_orcid_shows_a_form_error(self):
        response = self.client.post(
            reverse("as:user-create"), self._fields(orcid="123") | emails_formset()
        )
        self.assertContains(response, "Enter an ORCID iD like 0000-0002-1825-0097.")
        self.assertFalse(User.objects.exists())


class SimilarUserWarningTest(TestCase):
    def setUp(self):
        self.client.force_login(make_staff("as@example.com"))
        self.jane = make_user(
            "jane@example.org", name="Jane Smith", institution="Stanford"
        )

    def _post(self, url: str, **fields: str) -> "Response":
        data = {
            "name": "Jane Smyth",
            "preferred_name": "",
            "email": "smyth@example.org",
            "institution": "",
            "orcid": "",
            "credentials": "",
            "gpm_uuid": "",
        } | fields
        return self.client.post(url, data | emails_formset())

    def test_a_similar_name_isnt_saved_and_lists_the_match(self):
        response = self._post(reverse("as:user-create"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "might already be in the AS")
        self.assertContains(response, f'href="{self.jane.get_absolute_url()}"')
        self.assertContains(response, "jane@example.org")
        self.assertContains(response, "Stanford")
        self.assertContains(response, "Add Anyway")
        self.assertEqual(User.objects.count(), 1)

    def test_add_anyway_saves_the_user(self):
        response = self._post(reverse("as:user-create"), allow_similar_name="1")
        smyth = User.objects.get(name="Jane Smyth")
        self.assertRedirects(response, smyth.get_absolute_url())

    def test_a_name_with_no_match_saves_at_once(self):
        response = self._post(reverse("as:user-create"), name="Grace Hopper")
        grace = User.objects.get(name="Grace Hopper")
        self.assertRedirects(response, grace.get_absolute_url())

    def test_editing_a_user_doesnt_warn(self):
        smyth = make_user("smyth@example.org", name="Grace Hopper")
        url = reverse("as:user-edit", kwargs={"pk": smyth.pk})
        response = self._post(url)
        self.assertRedirects(response, smyth.get_absolute_url())
        smyth.refresh_from_db()
        self.assertEqual(smyth.name, "Jane Smyth")

    def test_a_taken_emails_error_links_the_user_who_has_it(self):
        UserEmail.objects.create(user=self.jane, email="js@uni.edu")
        for email in ["JANE@example.org", "js@uni.edu"]:
            with self.subTest(email=email):
                response = self._post(
                    reverse("as:user-create"), name="Grace Hopper", email=email
                )
                self.assertContains(
                    response,
                    f'<a href="{self.jane.get_absolute_url()}">Jane Smith</a> '
                    "already has this email.",
                    html=False,
                )
                self.assertNotContains(response, "Someone already has this email.")
        self.assertEqual(User.objects.count(), 1)

    def test_a_taken_other_emails_error_links_the_user_who_has_it(self):
        data = {
            "name": "Grace Hopper",
            "preferred_name": "",
            "email": "",
            "institution": "",
            "orcid": "",
            "credentials": "",
            "gpm_uuid": "",
        } | emails_formset("jane@example.org")
        response = self.client.post(reverse("as:user-create"), data)
        self.assertContains(
            response,
            f'<a href="{self.jane.get_absolute_url()}">Jane Smith</a> '
            "already has this email.",
        )


class UsersPermissionTest(TestCase):
    def test_users_pages_require_the_as_permission(self):
        ada = make_user()
        urls = [
            reverse("as:users"),
            reverse("as:user-create"),
            ada.get_absolute_url(),
            reverse("as:user-edit", kwargs={"pk": ada.pk}),
        ]
        self.client.force_login(make_staff("no-as@example.com", as_=False))
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
