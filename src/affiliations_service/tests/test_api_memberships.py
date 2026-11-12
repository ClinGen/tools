"""Houses tests for the AS API's membership endpoints."""

import uuid

from affiliations_service.models import Membership
from affiliations_service.tests.test_api_cdwgs import ApiTestCase
from affiliations_service.tests.test_memberships import (
    TODAY,
    TOMORROW,
    YESTERDAY,
    make_membership,
)
from affiliations_service.tests.test_models import make_affiliation
from affiliations_service.tests.test_users import make_user

URL = "/as/api/v1/memberships"


class MembershipListTest(ApiTestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.ada = make_user("ada@example.org", name="Ada")
        cls.grace = make_user("grace@example.org", name="Grace")
        cls.vcep = make_affiliation(full_name="VCEP")
        cls.gcep = make_affiliation(full_name="GCEP")
        cls.ada_coordinates = make_membership(
            cls.ada, cls.vcep, Membership.Role.COORDINATOR
        )
        cls.grace_curated = make_membership(
            cls.grace, cls.vcep, Membership.Role.CURATOR, end_date=YESTERDAY
        )
        cls.ada_approves = make_membership(cls.ada, cls.gcep, Membership.Role.APPROVER)

    def _ids(self, **params: str | int) -> set[str]:
        return {item["id"] for item in self.get(URL, **params).json()["items"]}

    def test_each_filter_narrows_the_list(self):
        cases = [
            ({}, [self.ada_coordinates, self.grace_curated, self.ada_approves]),
            (
                {"affiliation": str(self.vcep.pk)},
                [self.ada_coordinates, self.grace_curated],
            ),
            ({"user": str(self.ada.pk)}, [self.ada_coordinates, self.ada_approves]),
            ({"role": "APPROVER"}, [self.ada_approves]),
            ({"current": "true"}, [self.ada_coordinates, self.ada_approves]),
            ({"current": "false"}, [self.grace_curated]),
        ]
        for params, expected in cases:
            with self.subTest(params=params):
                self.assertEqual(self._ids(**params), {str(m.pk) for m in expected})

    def test_items_name_the_user_and_affiliation(self):
        item = self.get(URL, role="CURATOR").json()["items"][0]
        self.assertEqual(item["user"], str(self.grace.pk))
        self.assertEqual(item["affiliation"], str(self.vcep.pk))
        self.assertEqual(item["end_date"], YESTERDAY.isoformat())
        self.assertFalse(item["is_current"])


class MembershipChangeTest(ApiTestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.ada = make_user()
        cls.affiliation = make_affiliation()

    def _body(self, **fields: object) -> dict:
        return {
            "user": str(self.ada.pk),
            "affiliation": str(self.affiliation.pk),
            "role": "CURATOR",
        } | fields

    def test_create(self):
        response = self.post(URL, self._body(start_date=TODAY.isoformat()))
        self.assertEqual(response.status_code, 201)
        membership = Membership.objects.get()
        self.assertEqual(membership.start_date, TODAY)
        self.assertTrue(response.json()["is_current"])

    def test_a_duplicate_open_membership_returns_400(self):
        self.post(URL, self._body())
        response = self.post(URL, self._body())
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": "This user already holds this role in this affiliation."},
        )

    def test_unknown_user_or_affiliation_returns_400(self):
        for field in ["user", "affiliation"]:
            with self.subTest(field=field):
                response = self.post(URL, self._body(**{field: str(uuid.uuid4())}))
                self.assertEqual(response.status_code, 400)

    def test_a_deleted_affiliation_cant_get_members(self):
        self.affiliation.delete()
        self.assertEqual(self.post(URL, self._body()).status_code, 400)

    def test_ending_a_membership_with_patch(self):
        membership = make_membership(self.ada, self.affiliation)
        response = self.patch(f"{URL}/{membership.pk}", {"end_date": TODAY.isoformat()})
        self.assertEqual(response.status_code, 200)
        membership.refresh_from_db()
        self.assertEqual(membership.end_date, TODAY)
        self.assertEqual(self.get(URL, current="true").json()["count"], 0)

    def test_an_end_date_before_the_start_date_returns_400(self):
        membership = make_membership(self.ada, self.affiliation, start_date=TODAY)
        response = self.patch(
            f"{URL}/{membership.pk}", {"end_date": YESTERDAY.isoformat()}
        )
        self.assertEqual(response.status_code, 400)

    def test_patch_cant_change_the_user_or_role(self):
        membership = make_membership(self.ada, self.affiliation)
        response = self.patch(f"{URL}/{membership.pk}", {"role": "APPROVER"})
        self.assertEqual(response.status_code, 422)

    def test_deleting_a_membership_removes_it(self):
        membership = make_membership(self.ada, self.affiliation)
        self.assertEqual(self.delete(f"{URL}/{membership.pk}").status_code, 204)
        self.assertFalse(Membership.objects.filter(pk=membership.pk).exists())

    def test_unknown_id_returns_404(self):
        unknown = f"{URL}/{uuid.uuid4()}"
        self.assertEqual(self.get(unknown).status_code, 404)
        self.assertEqual(self.patch(unknown, {"end_date": None}).status_code, 404)

    def test_requests_without_a_key_get_401(self):
        self.assertEqual(self.client.get(URL).status_code, 401)


class DetailMembershipsTest(ApiTestCase):
    def test_affiliation_and_user_details_list_current_memberships(self):
        ada = make_user()
        affiliation = make_affiliation()
        current = make_membership(ada, affiliation, end_date=TOMORROW)
        make_membership(ada, affiliation, Membership.Role.APPROVER, end_date=YESTERDAY)
        for url in [
            f"/as/api/v1/affiliations/{affiliation.pk}",
            f"/as/api/v1/users/{ada.pk}",
        ]:
            with self.subTest(url=url):
                memberships = self.get(url).json()["current_memberships"]
                self.assertEqual([m["id"] for m in memberships], [str(current.pk)])
