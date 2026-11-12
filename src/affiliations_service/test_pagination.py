"""Houses tests for paging and sorting the AS's lists."""

from django.test import TestCase
from django.urls import reverse

from affiliations_service.models import Affiliation
from affiliations_service.tables import PER_PAGE
from affiliations_service.test_models import make_affiliation, make_cdwg
from affiliations_service.test_users import make_user
from affiliations_service.tests import make_staff

# Enough rows for a second page with five on it.
TOTAL = PER_PAGE + 5


class AffiliationPaginationTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cardio = make_cdwg("Cardiovascular")
        for number in range(TOTAL):
            make_affiliation(
                Affiliation.Type.VCEP, cdwg=cardio, full_name=f"Panel {number:03}"
            )

    def setUp(self):
        self.client.force_login(make_staff("as@example.com"))

    def _names(self, **params: str) -> list[str]:
        table = self.client.get(reverse("as:index"), params).context["table"]
        return [row.record.full_name for row in table.paginated_rows]

    def test_the_first_page_shows_100_and_links_to_page_2(self):
        response = self.client.get(reverse("as:index"))
        self.assertEqual(PER_PAGE, 100)
        self.assertEqual(len(self._names()), PER_PAGE)
        self.assertContains(response, "page=2")

    def test_page_2_shows_the_rest(self):
        self.assertEqual(
            self._names(page="2"), [f"Panel {n:03}" for n in range(PER_PAGE, TOTAL)]
        )

    def test_paging_keeps_the_search_and_filters(self):
        response = self.client.get(reverse("as:index"), {"q": "panel", "type": "VCEP"})
        page = response.content.decode()
        self.assertIn("q=panel", page)
        self.assertIn("type=VCEP", page)
        self.assertEqual(len(self._names(q="panel 02", page="1")), 10)

    def test_sorting_by_name(self):
        self.assertEqual(self._names(sort="-full_name")[0], f"Panel {TOTAL - 1:03}")


class OtherListPaginationTest(TestCase):
    def setUp(self):
        self.client.force_login(make_staff("as@example.com"))

    def test_the_user_and_cdwg_lists_page_too(self):
        for number in range(TOTAL):
            make_user(f"user{number}@example.org", name=f"User {number:03}")
            make_cdwg(f"CDWG {number:03}")
        for url in [reverse("as:users"), reverse("as:cdwgs")]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(
                    len(response.context["table"].paginated_rows), PER_PAGE
                )
                self.assertContains(response, "page=2")
