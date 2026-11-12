"""Houses tests for the person model."""

from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from affiliations_service.models import Person, PersonEmail
from affiliations_service.test_rules import errors_for

GPM_UUID = "6a1b5f0e-8f0c-4d7e-9a43-2b0f5d3c1e9a"


def make_person(email: str = "ada@example.org", **fields: object) -> Person:
    """Returns a new person with the given primary email.

    Args:
        email: The person's primary email.
        **fields: Any other fields to set.

    Returns:
        The saved person.
    """
    fields.setdefault("name", "Ada Lovelace")
    return Person.objects.create(email=email, **fields)


class PersonEmailTest(TestCase):
    def test_primary_emails_differing_only_in_case_collide(self):
        make_person("ada@example.org")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_person("ADA@example.org")
        self.assertIn("email", errors_for(Person(name="Ada", email="Ada@Example.org")))

    def test_other_emails_differing_only_in_case_collide(self):
        PersonEmail.objects.create(person=make_person(), email="ada@uni.edu")
        other = make_person("grace@example.org")
        with self.assertRaises(IntegrityError), transaction.atomic():
            PersonEmail.objects.create(person=other, email="ADA@uni.edu")

    def test_one_persons_primary_email_cant_be_anothers_other_email(self):
        make_person("ada@example.org")
        grace = make_person("grace@example.org")
        errors = errors_for(PersonEmail(person=grace, email="Ada@example.org"))
        self.assertIn("Someone already has this email.", str(errors))

    def test_one_persons_other_email_cant_be_anothers_primary_email(self):
        PersonEmail.objects.create(person=make_person(), email="ada@uni.edu")
        errors = errors_for(Person(name="Grace", email="ADA@uni.edu"))
        self.assertIn("Someone already has this email.", str(errors))

    def test_a_person_can_keep_their_own_email(self):
        ada = make_person()
        PersonEmail.objects.create(person=ada, email="ada@uni.edu")
        self.assertEqual(errors_for(ada), {})


class OrcidTest(TestCase):
    def test_valid_orcid_ids_pass(self):
        for orcid in ["0000-0002-1825-0097", "0000-0002-1694-233X"]:
            with self.subTest(orcid=orcid):
                person = Person(name="Ada", email="ada@example.org", orcid=orcid)
                self.assertEqual(errors_for(person), {})

    def test_bad_orcid_ids_fail(self):
        for orcid in ["0000-0002-1825", "0000000218250097", "0000-0002-1825-009Y"]:
            with self.subTest(orcid=orcid):
                person = Person(name="Ada", email="ada@example.org", orcid=orcid)
                self.assertIn("orcid", errors_for(person))

    def test_orcid_ids_are_unique_but_may_be_blank(self):
        make_person("ada@example.org", orcid="0000-0002-1825-0097")
        make_person("grace@example.org")
        make_person("alan@example.org")
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_person("bob@example.org", orcid="0000-0002-1825-0097")


class PersonTest(TestCase):
    def test_gpm_uuids_are_unique(self):
        make_person("ada@example.org", gpm_uuid=GPM_UUID)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_person("grace@example.org", gpm_uuid=GPM_UUID)

    def test_edits_record_history(self):
        person = make_person()
        person.institution = "Stanford University"
        person.save()
        self.assertEqual(person.history.count(), 2)  # type: ignore
        self.assertEqual(person.history.first().institution, "Stanford University")  # type: ignore

    def test_str_prefers_the_preferred_name(self):
        self.assertEqual(str(make_person(preferred_name="Ada L.")), "Ada L.")
        self.assertEqual(str(make_person("grace@example.org", name="Grace")), "Grace")


class PersonAdminTest(TestCase):
    def test_search_finds_a_person_by_an_other_email(self):
        ada = make_person()
        PersonEmail.objects.create(person=ada, email="countess@uni.edu")
        make_person("grace@example.org", name="Grace Hopper")
        self.client.force_login(
            User.objects.create_superuser("root", "r@example.com", "pw")
        )
        url = reverse("admin:affiliations_service_person_changelist")
        response = self.client.get(url, {"q": "countess"})
        self.assertContains(response, "Ada Lovelace")
        self.assertNotContains(response, "Grace Hopper")


class OptionalEmailTest(TestCase):
    def test_people_without_emails_can_coexist(self):
        make_person("", name="Approver One")
        make_person("", name="Approver Two")
        self.assertEqual(Person.objects.filter(email="").count(), 2)
        self.assertEqual(errors_for(Person(name="Approver Three", email="")), {})

    def test_set_emails_still_collide_ignoring_case(self):
        make_person("ada@example.org")
        self.assertIn("email", errors_for(Person(name="Ada", email="ADA@example.org")))
