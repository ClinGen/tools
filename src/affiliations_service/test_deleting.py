"""Houses tests for deleting records: affiliations softly, everything else for real."""

from affiliations_service.models import CDWG, Affiliation, Membership, User, UserEmail
from affiliations_service.test_api_cdwgs import ApiTestCase
from affiliations_service.test_memberships import make_membership
from affiliations_service.test_models import make_affiliation, make_cdwg
from affiliations_service.test_users import make_user

URL = "/as/api/v1"
GPM_UUID = "6a1b5f0e-8f0c-4d7e-9a43-2b0f5d3c1e9a"


class HardDeleteTest(ApiTestCase):
    def test_delete_removes_each_resource_and_keeps_its_history(self):
        membership = make_membership(make_user("grace@example.org"), make_affiliation())
        cdwg = make_cdwg("Kidney")
        user = make_user(name="Ada Lovelace")
        for resource, model, obj in [
            ("cdwgs", CDWG, cdwg),
            ("users", User, user),
            ("memberships", Membership, membership),
        ]:
            with self.subTest(resource=resource):
                response = self.delete(f"{URL}/{resource}/{obj.pk}")
                self.assertEqual(response.status_code, 204)
                self.assertFalse(model.objects.filter(pk=obj.pk).exists())
                last = model.history.filter(id=obj.pk).first()  # type: ignore
                self.assertEqual(last.history_type, "-")
        self.assertEqual(User.history.filter(id=user.pk).first().name, "Ada Lovelace")  # type: ignore

    def test_deleting_a_user_deletes_their_memberships_and_emails(self):
        user = make_user()
        UserEmail.objects.create(user=user, email="ada@uni.edu")
        membership = make_membership(user, make_affiliation())
        self.assertEqual(self.delete(f"{URL}/users/{user.pk}").status_code, 204)
        self.assertFalse(Membership.objects.filter(pk=membership.pk).exists())
        self.assertFalse(UserEmail.objects.exists())
        last = Membership.history.filter(id=membership.pk).first()  # type: ignore
        self.assertEqual(last.history_type, "-")

    def test_a_cdwg_with_affiliations_cant_be_deleted(self):
        affiliation = make_affiliation()
        affiliation.delete()
        cdwg = affiliation.cdwg
        response = self.delete(f"{URL}/cdwgs/{cdwg.pk}")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"detail": "This CDWG still has affiliations, so it can't be deleted."},
        )
        self.assertTrue(CDWG.objects.filter(pk=cdwg.pk).exists())

    def test_delete_by_gpm_uuid_deletes_cdwgs_and_users(self):
        cdwg = CDWG.objects.create(name="Kidney", gpm_uuid=GPM_UUID)
        user = make_user(gpm_uuid=GPM_UUID)
        for resource, model, obj in [("cdwgs", CDWG, cdwg), ("users", User, user)]:
            with self.subTest(resource=resource):
                response = self.delete(f"{URL}/{resource}/gpm-uuid/{GPM_UUID}")
                self.assertEqual(response.status_code, 204)
                self.assertFalse(model.objects.filter(pk=obj.pk).exists())

    def test_the_gpm_uuid_of_a_deleted_user_can_be_used_again(self):
        make_user(gpm_uuid=GPM_UUID)
        self.delete(f"{URL}/users/gpm-uuid/{GPM_UUID}")
        response = self.post(
            f"{URL}/users", {"name": "Ada Lovelace", "gpm_uuid": GPM_UUID}
        )
        self.assertEqual(response.status_code, 201)


class AffiliationSoftDeleteTest(ApiTestCase):
    def test_affiliations_are_still_soft_deleted(self):
        affiliation = make_affiliation(gpm_uuid=GPM_UUID)
        for url in [
            f"{URL}/affiliations/{affiliation.pk}",
            f"{URL}/affiliations/gpm-uuid/{GPM_UUID}",
        ]:
            with self.subTest(url=url):
                self.assertEqual(self.delete(url).status_code, 204)
                affiliation.refresh_from_db()
                self.assertTrue(affiliation.is_deleted)

    def test_a_deleted_affiliation_cant_get_new_memberships(self):
        affiliation = make_affiliation()
        affiliation.delete()
        response = self.post(
            f"{URL}/memberships",
            {
                "user": str(make_user().pk),
                "affiliation": str(affiliation.pk),
                "role": "CURATOR",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertTrue(Affiliation.objects.filter(pk=affiliation.pk).exists())
