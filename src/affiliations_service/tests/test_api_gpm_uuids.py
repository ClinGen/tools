"""Houses tests for the AS API's GPM UUID endpoints and checks."""

import uuid

from affiliations_service.models import CDWG, Affiliation, User
from affiliations_service.tests.test_api_cdwgs import ApiTestCase
from affiliations_service.tests.test_models import make_affiliation, make_cdwg
from affiliations_service.tests.test_users import make_user


class GpmUuidLookupTest(ApiTestCase):
    def test_finds_affiliations_cdwgs_and_users_by_gpm_uuid(self):
        affiliation = make_affiliation(gpm_uuid=GPM_UUID)
        cdwg = make_cdwg("Kidney")
        cdwg.gpm_uuid = GPM_UUID
        cdwg.save()
        user = make_user(gpm_uuid=GPM_UUID)
        for resource, obj in [
            ("affiliations", affiliation),
            ("cdwgs", cdwg),
            ("users", user),
        ]:
            with self.subTest(resource=resource):
                url = f"{URL}/{resource}/gpm-uuid/{GPM_UUID}"
                self.assertEqual(self.get(url).json()["id"], str(obj.pk))
                missing = f"{URL}/{resource}/gpm-uuid/{uuid.uuid4()}"
                self.assertEqual(self.get(missing).status_code, 404)


class GpmUuidInUseTest(ApiTestCase):
    def test_creating_with_a_gpm_uuid_in_use_is_refused(self):
        cdwg = make_affiliation(gpm_uuid=GPM_UUID).cdwg
        CDWG.objects.create(name="Kidney", gpm_uuid=GPM_UUID)
        make_user(gpm_uuid=GPM_UUID)
        cases = [
            (
                "affiliations",
                {"type": "GCEP", "full_name": "New", "cdwg": str(cdwg.pk)},
                "Another affiliation already has this GPM UUID.",
            ),
            ("cdwgs", {"name": "Ocular"}, "Another CDWG already has this GPM UUID."),
            (
                "users",
                {"name": "New Person", "email": "new@example.org"},
                "Another user already has this GPM UUID.",
            ),
        ]
        for resource, body, message in cases:
            with self.subTest(resource=resource):
                before = self.get(f"{URL}/{resource}").json()["count"]
                response = self.post(f"{URL}/{resource}", body | {"gpm_uuid": GPM_UUID})
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json(), {"detail": message})
                self.assertEqual(self.get(f"{URL}/{resource}").json()["count"], before)


class GpmUuidChangeTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.affiliation = make_affiliation(Affiliation.Type.GCEP, gpm_uuid=GPM_UUID)
        self.cdwg = make_cdwg("Kidney")
        self.cdwg.gpm_uuid = GPM_UUID
        self.cdwg.save()
        self.user = make_user(gpm_uuid=GPM_UUID)

    def test_patch_by_gpm_uuid_changes_each_resource(self):
        cases = [
            ("affiliations", self.affiliation, {"full_name": "Renamed"}, "full_name"),
            ("cdwgs", self.cdwg, {"name": "Renal"}, "name"),
            ("users", self.user, {"institution": "Stanford"}, "institution"),
        ]
        for resource, obj, change, field in cases:
            with self.subTest(resource=resource):
                response = self.patch(f"{URL}/{resource}/gpm-uuid/{GPM_UUID}", change)
                self.assertEqual(response.status_code, 200)
                obj.refresh_from_db()
                self.assertEqual(getattr(obj, field), change[field])

    def test_delete_by_gpm_uuid(self):
        for resource in ["affiliations", "cdwgs", "users"]:
            with self.subTest(resource=resource):
                response = self.delete(f"{URL}/{resource}/gpm-uuid/{GPM_UUID}")
                self.assertEqual(response.status_code, 204)
        # Affiliations are kept and marked deleted; CDWGs and users are deleted.
        self.affiliation.refresh_from_db()
        self.assertTrue(self.affiliation.is_deleted)
        self.assertFalse(CDWG.objects.filter(pk=self.cdwg.pk).exists())
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())

    def test_unknown_gpm_uuids_return_404(self):
        missing = uuid.uuid4()
        for resource in ["affiliations", "cdwgs", "users"]:
            with self.subTest(resource=resource):
                url = f"{URL}/{resource}/gpm-uuid/{missing}"
                self.assertEqual(self.patch(url, {}).status_code, 404)
                self.assertEqual(self.delete(url).status_code, 404)

    def test_locked_affiliation_fields_cant_change_by_gpm_uuid(self):
        url = f"{URL}/affiliations/gpm-uuid/{GPM_UUID}"
        self.assertEqual(self.patch(url, {"type": "VCEP"}).status_code, 400)
        self.affiliation.refresh_from_db()
        self.assertEqual(self.affiliation.type, Affiliation.Type.GCEP)


URL = "/as/api/v1"


GPM_UUID = "6a1b5f0e-8f0c-4d7e-9a43-2b0f5d3c1e9a"
