"""Houses tests for the affiliation list and detail pages."""

import re

from django.test import TestCase
from django.urls import reverse

from affiliations_service.models import Affiliation, ClinVarSubmitterId, Membership
from affiliations_service.tests.helpers import make_staff
from affiliations_service.tests.test_memberships import YESTERDAY, make_membership
from affiliations_service.tests.test_models import make_affiliation, make_cdwg
from affiliations_service.tests.test_users import make_user


class AffiliationListPageTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.cardio = make_cdwg("Cardiovascular")
        cls.kidney = make_cdwg("Kidney")
        cls.vcep = make_affiliation(
            Affiliation.Type.VCEP,
            cdwg=cls.cardio,
            full_name="Cardiomyopathy VCEP",
            status=Affiliation.Status.ACTIVE,
        )
        cls.gcep = make_affiliation(
            Affiliation.Type.GCEP, cdwg=cls.kidney, full_name="Kidney Cystic GCEP"
        )
        make_affiliation(cdwg=cls.cardio, full_name="Gone VCEP").delete()

    def setUp(self):
        self.client.force_login(make_staff("as@example.com"))

    def _page(self, **params: str | int) -> str:
        return self.client.get(reverse("as:index"), params).content.decode()

    def test_lists_affiliations_without_deleted_ones(self):
        page = self._page()
        self.assertIn("Cardiomyopathy VCEP", page)
        self.assertIn("Kidney Cystic GCEP", page)
        self.assertNotIn("Gone VCEP", page)

    def test_search_and_filters_narrow_the_list(self):
        cases = [
            ({"q": "cystic"}, "Kidney Cystic GCEP", "Cardiomyopathy VCEP"),
            (
                {"q": str(self.vcep.affiliation_id)},
                "Cardiomyopathy VCEP",
                "Kidney Cystic GCEP",
            ),
            (
                {"q": str(self.gcep.expert_panel_id)},
                "Kidney Cystic GCEP",
                "Cardiomyopathy VCEP",
            ),
            ({"type": "VCEP"}, "Cardiomyopathy VCEP", "Kidney Cystic GCEP"),
            ({"status": "ACTIVE"}, "Cardiomyopathy VCEP", "Kidney Cystic GCEP"),
            (
                {"cdwg": str(self.kidney.pk)},
                "Kidney Cystic GCEP",
                "Cardiomyopathy VCEP",
            ),
        ]
        for params, shown, hidden in cases:
            with self.subTest(params=params):
                page = self._page(**params)
                self.assertIn(shown, page)
                self.assertNotIn(hidden, page)

    def test_links_to_each_affiliation(self):
        self.assertIn(self.vcep.get_absolute_url(), self._page())

    def test_says_when_nothing_matches(self):
        self.assertIn("No affiliations match.", self._page(q="nothing"))


class AffiliationDetailPageTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.affiliation = make_affiliation(
            Affiliation.Type.GCEP, full_name="Kidney Cystic GCEP"
        )
        ClinVarSubmitterId.objects.create(
            affiliation=cls.affiliation, submitter_id="500123"
        )
        cls.ada = make_user("ada@example.org", name="Ada Lovelace")
        cls.grace = make_user("grace@example.org", name="Grace Hopper")
        make_membership(cls.ada, cls.affiliation, Membership.Role.COORDINATOR)
        make_membership(
            cls.grace, cls.affiliation, Membership.Role.CURATOR, end_date=YESTERDAY
        )

    def setUp(self):
        self.user = make_staff("as@example.com")
        self.client.force_login(self.user)

    def _page(self) -> str:
        return self.client.get(self.affiliation.get_absolute_url()).content.decode()

    def test_shows_the_affiliations_fields(self):
        page = self._page()
        for text in ["Kidney Cystic GCEP", "10000", "40000", "500123", "Applying"]:
            with self.subTest(text=text):
                self.assertIn(text, page)

    def test_shows_current_members_by_role_and_past_members_separately(self):
        page = self._page()
        current_start = page.index("Current Members")
        past_start = page.index("Past Members")
        self.assertIn("Ada Lovelace", page[current_start:past_start])
        self.assertIn("Coordinator", page[current_start:past_start])
        self.assertIn("Grace Hopper", page[past_start:])
        self.assertNotIn("Grace Hopper", page[current_start:past_start])

    def test_shows_history_in_plain_language(self):
        self.affiliation.status = Affiliation.Status.ACTIVE
        self.affiliation._history_user = self.user  # type: ignore  # ruff: ignore[private-member-access]
        self.affiliation.save()
        page = self._page()
        self.assertIn("Changed Status from Applying to Active.", page)
        self.assertIn("Added the affiliation.", page)
        self.assertIn("as@example.com", page)

    def test_doesnt_show_uuids(self):
        page = self._page()
        for obj in [self.affiliation, self.affiliation.cdwg, self.ada]:
            with self.subTest(obj=obj):
                # URLs may hold IDs; the text staff read may not.
                text = re.sub(r'(href|action|hx-[a-z]+|value)="[^"]*"', "", page)
                self.assertNotIn(str(obj.pk), text)

    def test_deleted_affiliation_says_so(self):
        self.affiliation.delete()
        self.assertIn("This affiliation has been deleted.", self._page())


class PagePermissionTest(TestCase):
    def test_pages_require_the_as_permission(self):
        affiliation = make_affiliation()
        urls = [reverse("as:index"), affiliation.get_absolute_url()]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(make_staff("no-as@example.com", as_=False))
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 403)
