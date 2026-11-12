"""Houses tests for the user model."""

from django.contrib.auth.models import User as StaffUser
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from affiliations_service.models import User, UserEmail
from affiliations_service.tests.test_rules import errors_for

GPM_UUID = "6a1b5f0e-8f0c-4d7e-9a43-2b0f5d3c1e9a"


def make_user(email: str = "ada@example.org", **fields: object) -> User:
    """Returns a new user with the given primary email.

    Args:
        email: The user's primary email.
        **fields: Any other fields to set.

    Returns:
        The saved user.
    """
    fields.setdefault("name", "Ada Lovelace")
    return User.objects.create(email=email, **fields)


class UserEmailTest(TestCase):
    def test_primary_emails_differing_only_in_case_collide(self):
        make_user("ada@example.org")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_user("ADA@example.org")
        self.assertIn("email", errors_for(User(name="Ada", email="Ada@Example.org")))

    def test_other_emails_differing_only_in_case_collide(self):
        UserEmail.objects.create(user=make_user(), email="ada@uni.edu")
        other = make_user("grace@example.org")
        with self.assertRaises(IntegrityError), transaction.atomic():
            UserEmail.objects.create(user=other, email="ADA@uni.edu")

    def test_one_users_primary_email_cant_be_anothers_other_email(self):
        make_user("ada@example.org")
        grace = make_user("grace@example.org")
        errors = errors_for(UserEmail(user=grace, email="Ada@example.org"))
        self.assertIn("Someone already has this email.", str(errors))

    def test_one_users_other_email_cant_be_anothers_primary_email(self):
        UserEmail.objects.create(user=make_user(), email="ada@uni.edu")
        errors = errors_for(User(name="Grace", email="ADA@uni.edu"))
        self.assertIn("Someone already has this email.", str(errors))

    def test_a_user_can_keep_their_own_email(self):
        ada = make_user()
        UserEmail.objects.create(user=ada, email="ada@uni.edu")
        self.assertEqual(errors_for(ada), {})


class OrcidTest(TestCase):
    def test_valid_orcid_ids_pass(self):
        for orcid in ["0000-0002-1825-0097", "0000-0002-1694-233X"]:
            with self.subTest(orcid=orcid):
                user = User(name="Ada", email="ada@example.org", orcid=orcid)
                self.assertEqual(errors_for(user), {})

    def test_bad_orcid_ids_fail(self):
        for orcid in ["0000-0002-1825", "0000000218250097", "0000-0002-1825-009Y"]:
            with self.subTest(orcid=orcid):
                user = User(name="Ada", email="ada@example.org", orcid=orcid)
                self.assertIn("orcid", errors_for(user))

    def test_orcid_ids_are_unique_but_may_be_blank(self):
        make_user("ada@example.org", orcid="0000-0002-1825-0097")
        make_user("grace@example.org")
        make_user("alan@example.org")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_user("bob@example.org", orcid="0000-0002-1825-0097")


class UserTest(TestCase):
    def test_gpm_uuids_are_unique(self):
        make_user("ada@example.org", gpm_uuid=GPM_UUID)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_user("grace@example.org", gpm_uuid=GPM_UUID)

    def test_edits_record_history(self):
        user = make_user()
        user.institution = "Stanford University"
        user.save()
        self.assertEqual(user.history.count(), 2)  # type: ignore
        self.assertEqual(user.history.first().institution, "Stanford University")  # type: ignore

    def test_str_prefers_the_preferred_name(self):
        self.assertEqual(str(make_user(preferred_name="Ada L.")), "Ada L.")
        self.assertEqual(str(make_user("grace@example.org", name="Grace")), "Grace")


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


class OptionalEmailTest(TestCase):
    def test_users_without_emails_can_coexist(self):
        make_user("", name="Approver One")
        make_user("", name="Approver Two")
        self.assertEqual(User.objects.filter(email="").count(), 2)
        self.assertEqual(errors_for(User(name="Approver Three", email="")), {})

    def test_set_emails_still_collide_ignoring_case(self):
        make_user("ada@example.org")
        self.assertIn("email", errors_for(User(name="Ada", email="ADA@example.org")))
