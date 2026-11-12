"""Houses tests for the AS's Django admin pages."""

from django.contrib import admin
from django.contrib.auth.models import Permission
from django.contrib.auth.models import User as StaffUser
from django.forms import model_to_dict
from django.test import RequestFactory, TestCase
from django.urls import reverse

from affiliations_service.models import Affiliation, ApiKey, UserEmail
from affiliations_service.tests.test_memberships import make_membership
from affiliations_service.tests.test_models import make_affiliation
from affiliations_service.tests.test_users import make_user


class ApiKeyAdminTest(TestCase):
    def test_creating_a_key_in_the_admin_shows_it_once(self):
        self.client.force_login(
            StaffUser.objects.create_superuser("root", "r@example.com", "pw")
        )
        response = self.client.post(
            reverse("admin:affiliations_service_apikey_add"),
            {"name": "GCI", "is_active": "on"},
            follow=True,
        )
        api_key = ApiKey.objects.get()
        self.assertContains(response, "be shown again")
        self.assertContains(response, api_key.prefix)
        self.assertEqual(len(api_key.key_hash), 64)


class MembershipAdminTest(TestCase):
    def test_memberships_show_inline_on_affiliations_and_users(self):
        user = make_user()
        affiliation = make_affiliation()
        make_membership(user, affiliation)
        self.client.force_login(
            StaffUser.objects.create_superuser("root", "r@example.com", "pw")
        )
        for name, obj in [("affiliation", affiliation), ("user", user)]:
            with self.subTest(page=name):
                url = reverse(
                    f"admin:affiliations_service_{name}_change", args=[obj.pk]
                )
                self.assertContains(self.client.get(url), "memberships-TOTAL_FORMS")


class UserAdminTest(TestCase):
    def test_search_finds_a_user_by_an_other_email(self):
        ada = make_user()
        UserEmail.objects.create(user=ada, email="countess@uni.edu")
        make_user("grace@example.org", name="Grace Hopper")
        self.client.force_login(
            StaffUser.objects.create_superuser("root", "r@example.com", "pw")
        )
        url = reverse("admin:affiliations_service_user_changelist")
        response = self.client.get(url, {"q": "countess"})
        self.assertContains(response, "Ada Lovelace")
        self.assertNotContains(response, "Grace Hopper")


class AdminLockedFieldsTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.affiliation = make_affiliation(Affiliation.Type.GCEP)
        cls.superuser = StaffUser.objects.create_superuser(
            "root", "root@example.com", "pw"
        )
        cls.staff = StaffUser.objects.create_user("staff", "staff@example.com", "pw")
        cls.staff.is_staff = True
        cls.staff.save()
        cls.staff.user_permissions.add(
            *Permission.objects.filter(
                codename__in=["view_affiliation", "change_affiliation"]
            )
        )

    def _change_page(self, user: StaffUser) -> str:
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


LOCKED_FIELDS = ["affiliation_id", "expert_panel_id", "type", "gpm_uuid"]
