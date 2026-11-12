"""Houses tests for soft-deleting CDWGs, users, and memberships."""

from django.urls import reverse

from affiliations_service.models import CDWG, Affiliation, Membership, User
from affiliations_service.test_api_cdwgs import ApiTestCase
from affiliations_service.test_memberships import make_membership
from affiliations_service.test_models import make_affiliation, make_cdwg
from affiliations_service.test_users import make_user
from affiliations_service.tests import make_staff

URL = "/as/api/v1"


class DeleteEndpointTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.affiliation = make_affiliation()
        self.user = make_user()
        self.membership = make_membership(self.user, self.affiliation)
        self.cdwg = make_cdwg("Kidney")

    def test_delete_soft_deletes_each_resource(self):
        for resource, obj in [
            ("cdwgs", self.cdwg),
            ("users", self.user),
            ("memberships", self.membership),
        ]:
            with self.subTest(resource=resource):
                response = self.delete(f"{URL}/{resource}/{obj.pk}")
                self.assertEqual(response.status_code, 204)
                obj.refresh_from_db()
                self.assertTrue(obj.is_deleted)
                self.assertTrue(obj.history.first().is_deleted)  # type: ignore

    def test_deleted_records_are_hidden_from_lists_but_found_by_id(self):
        for obj in [self.cdwg, self.user, self.membership]:
            obj.delete()
        for resource, obj in [
            ("cdwgs", self.cdwg),
            ("users", self.user),
            ("memberships", self.membership),
        ]:
            with self.subTest(resource=resource):
                ids = [
                    item["id"] for item in self.get(f"{URL}/{resource}").json()["items"]
                ]
                self.assertNotIn(str(obj.pk), ids)
                body = self.get(f"{URL}/{resource}", include_deleted="true").json()
                self.assertIn(str(obj.pk), [item["id"] for item in body["items"]])
                detail = self.get(f"{URL}/{resource}/{obj.pk}").json()
                self.assertTrue(detail["is_deleted"])

    def test_unknown_ids_return_404(self):
        for resource in ["cdwgs", "users", "memberships"]:
            with self.subTest(resource=resource):
                url = f"{URL}/{resource}/6a1b5f0e-8f0c-4d7e-9a43-2b0f5d3c1e9a"
                self.assertEqual(self.delete(url).status_code, 404)


class DeletedRecordRulesTest(ApiTestCase):
    def test_a_deleted_membership_isnt_current_and_doesnt_block_the_role(self):
        user, affiliation = make_user(), make_affiliation()
        membership = make_membership(user, affiliation)
        membership.delete()
        self.assertFalse(Membership.objects.current().exists())
        membership.refresh_from_db()
        self.assertFalse(membership.is_current)
        response = self.post(
            f"{URL}/memberships",
            {
                "user": str(user.pk),
                "affiliation": str(affiliation.pk),
                "role": "CURATOR",
            },
        )
        self.assertEqual(response.status_code, 201)

    def test_a_deleted_user_cant_get_new_memberships(self):
        user, affiliation = make_user(), make_affiliation()
        user.delete()
        response = self.post(
            f"{URL}/memberships",
            {
                "user": str(user.pk),
                "affiliation": str(affiliation.pk),
                "role": "CURATOR",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "This user has been deleted."})

    def test_a_deleted_cdwg_cant_get_new_affiliations(self):
        cdwg = make_cdwg("Kidney")
        cdwg.delete()
        response = self.post(
            f"{URL}/affiliations",
            {"type": "GCEP", "full_name": "New GCEP", "cdwg": str(cdwg.pk)},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json(), {"detail": "That CDWG has been deleted."})

    def test_an_affiliation_whose_cdwg_was_deleted_can_still_be_changed(self):
        affiliation = make_affiliation()
        affiliation.cdwg.delete()
        response = self.patch(
            f"{URL}/affiliations/{affiliation.pk}", {"full_name": "Renamed"}
        )
        self.assertEqual(response.status_code, 200)

    def test_deleting_a_user_keeps_their_memberships(self):
        user, affiliation = make_user(), make_affiliation()
        make_membership(user, affiliation)
        user.delete()
        self.assertEqual(Membership.objects.active().count(), 1)


class StaffPagesHideDeletedTest(ApiTestCase):
    def test_the_user_and_cdwg_lists_leave_deleted_records_out(self):
        self.client.force_login(make_staff("as@example.com"))
        make_user("gone@example.org", name="Gone User").delete()
        make_cdwg("Gone CDWG").delete()
        self.assertNotContains(self.client.get(reverse("as:users")), "Gone User")
        self.assertNotContains(self.client.get(reverse("as:cdwgs")), "Gone CDWG")
        search = self.client.get(reverse("as:user-search"), {"q": "gone"})
        self.assertNotContains(search, "Gone User")

    def test_the_new_affiliation_form_leaves_deleted_cdwgs_out(self):
        self.client.force_login(make_staff("as@example.com"))
        gone = make_cdwg("Gone CDWG")
        gone.delete()
        page = self.client.get(reverse("as:affiliation-create")).content.decode()
        self.assertNotIn("Gone CDWG", page)
        self.assertTrue(CDWG.objects.filter(pk=gone.pk).exists())
        self.assertFalse(Affiliation.objects.exists())
        self.assertFalse(User.objects.exists())
