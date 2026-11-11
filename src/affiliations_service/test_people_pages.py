"""Houses tests for the people pages."""

from django.test import TestCase
from django.urls import reverse

from affiliations_service.models import Membership, Person, PersonEmail
from affiliations_service.test_memberships import YESTERDAY, make_membership
from affiliations_service.test_models import make_affiliation
from affiliations_service.test_people import make_person
from affiliations_service.tests import make_user


def emails_formset(*emails: str, existing: tuple[PersonEmail, ...] = ()) -> dict:
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


class PersonListPageTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.ada = make_person("ada@example.org", name="Ada Lovelace")
        PersonEmail.objects.create(person=cls.ada, email="countess@uni.edu")
        cls.grace = make_person("grace@example.org", name="Grace Hopper")

    def setUp(self):
        self.client.force_login(make_user("as@example.com"))

    def _page(self, **params: str) -> str:
        return self.client.get(reverse("as:people"), params).content.decode()

    def test_lists_people_and_links_to_them(self):
        page = self._page()
        self.assertIn("Ada Lovelace", page)
        self.assertIn(self.grace.get_absolute_url(), page)

    def test_search_finds_people_by_name_and_other_email(self):
        self.assertNotIn("Ada Lovelace", self._page(q="hopper"))
        page = self._page(q="countess")
        self.assertIn("Ada Lovelace", page)
        self.assertNotIn("Grace Hopper", page)

    def test_the_tabs_link_to_the_people_list(self):
        self.assertContains(self.client.get(reverse("as:index")), reverse("as:people"))


class PersonDetailPageTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.ada = make_person(
            "ada@example.org", name="Ada Lovelace", orcid="0000-0002-1825-0097"
        )
        PersonEmail.objects.create(person=cls.ada, email="countess@uni.edu")
        cls.vcep = make_affiliation(full_name="Cardiomyopathy VCEP")
        cls.gcep = make_affiliation(full_name="Kidney GCEP")
        make_membership(cls.ada, cls.vcep, Membership.Role.COORDINATOR)
        make_membership(cls.ada, cls.gcep, Membership.Role.CURATOR, end_date=YESTERDAY)

    def setUp(self):
        self.client.force_login(make_user("as@example.com"))

    def test_shows_fields_memberships_and_history(self):
        page = self.client.get(self.ada.get_absolute_url()).content.decode()
        current_start = page.index("Current Affiliations")
        past_start = page.index("Past Affiliations")
        for text in ["countess@uni.edu", "0000-0002-1825-0097", "Added the person."]:
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


class PersonFormPageTest(TestCase):
    def setUp(self):
        self.client.force_login(make_user("as@example.com"))

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
            reverse("as:person-create"), self._fields() | emails_formset("ada@uni.edu")
        )
        ada = Person.objects.get()
        self.assertRedirects(response, ada.get_absolute_url())
        self.assertEqual([e.email for e in ada.other_emails.all()], ["ada@uni.edu"])  # type: ignore

    def test_edit_adds_and_removes_other_emails(self):
        ada = make_person()
        old = PersonEmail.objects.create(person=ada, email="old@uni.edu")
        formset = emails_formset("new@uni.edu", existing=(old,))
        formset["other_emails-0-DELETE"] = "on"
        url = reverse("as:person-edit", kwargs={"pk": ada.pk})
        response = self.client.post(url, self._fields(institution="Stanford") | formset)
        self.assertRedirects(response, ada.get_absolute_url())
        ada.refresh_from_db()
        self.assertEqual(ada.institution, "Stanford")
        self.assertEqual([e.email for e in ada.other_emails.all()], ["new@uni.edu"])  # type: ignore

    def test_duplicate_emails_show_form_errors(self):
        grace = make_person("grace@example.org", name="Grace Hopper")
        PersonEmail.objects.create(person=grace, email="grace@uni.edu")
        cases = [
            self._fields(email="GRACE@example.org") | emails_formset(),
            self._fields() | emails_formset("Grace@Uni.edu"),
            self._fields() | emails_formset("ada@example.org"),
        ]
        for data in cases:
            with self.subTest(data=data):
                response = self.client.post(reverse("as:person-create"), data)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(
                    "Someone already has this email." in response.content.decode()
                    or "This is already the person&#x27;s main email."
                    in response.content.decode()
                )
        self.assertEqual(Person.objects.count(), 1)

    def test_bad_orcid_shows_a_form_error(self):
        response = self.client.post(
            reverse("as:person-create"), self._fields(orcid="123") | emails_formset()
        )
        self.assertContains(response, "Enter an ORCID iD like 0000-0002-1825-0097.")
        self.assertFalse(Person.objects.exists())


class PeoplePermissionTest(TestCase):
    def test_people_pages_require_the_as_permission(self):
        ada = make_person()
        urls = [
            reverse("as:people"),
            reverse("as:person-create"),
            ada.get_absolute_url(),
            reverse("as:person-edit", kwargs={"pk": ada.pk}),
        ]
        self.client.force_login(make_user("no-as@example.com", as_=False))
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
