"""Houses tests for the AS's business rules and the admin's locked IDs."""

from django.contrib import admin
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.forms import model_to_dict
from django.test import RequestFactory, TestCase
from django.urls import reverse

from affiliations_service.models import CDWG, Affiliation
from affiliations_service.test_models import make_affiliation, make_cdwg

LOCKED_FIELDS = ["affiliation_id", "expert_panel_id", "type", "gpm_uuid"]
GPM_UUID = "6a1b5f0e-8f0c-4d7e-9a43-2b0f5d3c1e9a"


def errors_for(instance: object) -> dict[str, list[str]]:
    """Returns the errors full_clean() raises for an instance, or an empty dict."""
    try:
        instance.full_clean()  # type: ignore
    except ValidationError as error:
        return error.message_dict
    return {}


class AffiliationRuleTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.cardio = make_cdwg("Cardiovascular")
        cls.somatic = make_cdwg("Somatic Cancer")
        cls.none = make_cdwg("None")

    def _affiliation(self, type_: str, cdwg: CDWG, **fields: object) -> Affiliation:
        return Affiliation(type=type_, cdwg=cdwg, full_name="Test", **fields)

    def test_independent_group_cant_have_a_gpm_uuid(self):
        affiliation = self._affiliation(
            Affiliation.Type.INDEPENDENT_CURATION, self.none, gpm_uuid=GPM_UUID
        )
        self.assertIn("gpm_uuid", errors_for(affiliation))

    def test_independent_group_must_be_in_the_none_cdwg(self):
        bad = self._affiliation(Affiliation.Type.INDEPENDENT_CURATION, self.cardio)
        good = self._affiliation(Affiliation.Type.INDEPENDENT_CURATION, self.none)
        self.assertIn("cdwg", errors_for(bad))
        self.assertEqual(errors_for(good), {})

    def test_sc_vcep_must_be_in_the_somatic_cancer_cdwg(self):
        bad = self._affiliation(Affiliation.Type.SC_VCEP, self.cardio)
        good = self._affiliation(Affiliation.Type.SC_VCEP, self.somatic)
        self.assertIn("cdwg", errors_for(bad))
        self.assertEqual(errors_for(good), {})

    def test_other_types_may_be_in_any_cdwg(self):
        for type_ in [Affiliation.Type.VCEP, Affiliation.Type.GCEP]:
            with self.subTest(type=type_):
                affiliation = self._affiliation(type_, self.cardio, gpm_uuid=GPM_UUID)
                self.assertEqual(errors_for(affiliation), {})

    def test_cdwg_names_differing_only_in_case_fail_validation(self):
        errors = errors_for(CDWG(name="somatic cancer"))
        self.assertIn("There's already a CDWG with this name.", str(errors))


class IdRuleTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.cdwg = make_cdwg()

    def _affiliation(
        self, type_: str, affiliation_id: int, expert_panel_id: int | None
    ) -> Affiliation:
        return Affiliation(
            type=type_,
            cdwg=self.cdwg,
            full_name="Test",
            affiliation_id=affiliation_id,
            expert_panel_id=expert_panel_id,
        )

    def test_matching_ids_pass(self):
        cases = [
            (Affiliation.Type.GCEP, 10042, 40042),
            (Affiliation.Type.VCEP, 10042, 50042),
            (Affiliation.Type.SC_VCEP, 10042, 50042),
        ]
        for type_, affiliation_id, expert_panel_id in cases:
            with self.subTest(type=type_):
                affiliation = self._affiliation(type_, affiliation_id, expert_panel_id)
                errors = errors_for(affiliation)
                self.assertNotIn("affiliation_id", errors)
                self.assertNotIn("expert_panel_id", errors)

    def test_out_of_range_ids_fail(self):
        cases = [
            (Affiliation.Type.GCEP, 9999, 49999, "affiliation_id"),
            (Affiliation.Type.GCEP, 20000, 40000, "affiliation_id"),
            (Affiliation.Type.GCEP, 10042, 50042, "expert_panel_id"),
            (Affiliation.Type.VCEP, 10042, 40042, "expert_panel_id"),
        ]
        for type_, affiliation_id, expert_panel_id, field in cases:
            with self.subTest(type=type_, ids=(affiliation_id, expert_panel_id)):
                affiliation = self._affiliation(type_, affiliation_id, expert_panel_id)
                self.assertIn(field, errors_for(affiliation))

    def test_mismatched_suffixes_fail(self):
        affiliation = self._affiliation(Affiliation.Type.GCEP, 10042, 40043)
        self.assertIn("expert_panel_id", errors_for(affiliation))

    def test_independent_group_cant_have_an_expert_panel_id(self):
        none = make_cdwg("None")
        affiliation = self._affiliation(
            Affiliation.Type.INDEPENDENT_CURATION, 10042, 40042
        )
        affiliation.cdwg = none
        self.assertIn("expert_panel_id", errors_for(affiliation))

    def test_duplicate_ids_fail_with_plain_messages(self):
        make_affiliation(Affiliation.Type.GCEP, cdwg=self.cdwg, affiliation_id=10042)
        same_affiliation_id = self._affiliation(Affiliation.Type.GCEP, 10042, None)
        same_expert_panel_id = self._affiliation(Affiliation.Type.GCEP, 11042, 40042)
        self.assertIn(
            "Another affiliation of this type already has this affiliation ID.",
            str(errors_for(same_affiliation_id)),
        )
        self.assertIn(
            "Another affiliation already has this expert panel ID.",
            str(errors_for(same_expert_panel_id)),
        )


class AdminLockedFieldsTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.affiliation = make_affiliation(Affiliation.Type.GCEP)
        cls.superuser = User.objects.create_superuser("root", "root@example.com", "pw")
        cls.staff = User.objects.create_user("staff", "staff@example.com", "pw")
        cls.staff.is_staff = True
        cls.staff.save()
        cls.staff.user_permissions.add(
            *Permission.objects.filter(
                codename__in=["view_affiliation", "change_affiliation"]
            )
        )

    def _change_page(self, user: User) -> str:
        self.client.force_login(user)
        url = reverse(
            "admin:affiliations_service_affiliation_change", args=[self.affiliation.pk]
        )
        return self.client.get(url).content.decode()

    def test_staff_see_the_locked_fields_read_only(self):
        page = self._change_page(self.staff)
        for field in LOCKED_FIELDS:
            with self.subTest(field=field):
                self.assertNotIn(f'name="{field}"', page)
        self.assertIn('name="full_name"', page)

    def test_superusers_can_edit_the_locked_fields(self):
        page = self._change_page(self.superuser)
        for field in LOCKED_FIELDS:
            with self.subTest(field=field):
                self.assertIn(f'name="{field}"', page)

    def test_superuser_form_rejects_a_mismatched_edit_and_accepts_a_valid_one(self):
        request = RequestFactory().get("/")
        request.user = self.superuser
        model_admin = admin.site._registry[Affiliation]  # ruff: ignore[private-member-access]
        form_class = model_admin.get_form(request, self.affiliation)
        data = model_to_dict(self.affiliation)
        data["expert_panel_id"] = 40999
        self.assertFalse(form_class(data, instance=self.affiliation).is_valid())
        data["affiliation_id"] = 10999
        self.assertTrue(form_class(data, instance=self.affiliation).is_valid())
