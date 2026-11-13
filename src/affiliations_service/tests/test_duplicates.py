"""Houses tests for finding users who may already be in the AS."""

from django.test import TestCase

from affiliations_service.duplicates import similar_users
from affiliations_service.models import UserEmail, user_with_email
from affiliations_service.tests.test_users import make_user


class SimilarUsersTest(TestCase):
    def test_names_differing_in_case_accents_and_punctuation_match(self):
        jose = make_user("jose@example.org", name="José O'Brien-Núñez")
        self.assertEqual(similar_users("jose obrien nunez"), [jose])

    def test_the_same_names_in_another_order_match(self):
        jane = make_user("jane@example.org", name="Jane Smith")
        self.assertEqual(similar_users("Smith, Jane"), [jane])

    def test_a_one_letter_typo_matches(self):
        jane = make_user("jane@example.org", name="Jane Smith")
        self.assertEqual(similar_users("Jane Smyth"), [jane])

    def test_a_preferred_name_matches(self):
        bob = make_user("bob@example.org", name="Robert Jones", preferred_name="Bob")
        self.assertEqual(similar_users("Bob"), [bob])
        self.assertEqual(
            similar_users("Bobby Jones", preferred_name="Robert Jones"), [bob]
        )

    def test_clearly_different_names_dont_match(self):
        make_user("ada@example.org", name="Ada Lovelace")
        make_user("john@example.org", name="John Smith")
        self.assertEqual(similar_users("Grace Hopper"), [])
        self.assertEqual(similar_users("Jane Smith"), [])

    def test_the_best_match_comes_first(self):
        close = make_user("smyth@example.org", name="Jane Smyth")
        exact = make_user("smith@example.org", name="Jane Smith")
        self.assertEqual(similar_users("Jane Smith"), [exact, close])

    def test_a_blank_name_matches_no_one(self):
        make_user("ada@example.org", name="Ada Lovelace")
        self.assertEqual(similar_users(" , "), [])


class UserWithEmailTest(TestCase):
    def test_finds_the_user_by_their_main_email_ignoring_case(self):
        ada = make_user("ada@example.org")
        self.assertEqual(user_with_email("ADA@example.org"), ada)

    def test_finds_the_user_by_an_other_email(self):
        ada = make_user("ada@example.org")
        UserEmail.objects.create(user=ada, email="lovelace@example.org")
        self.assertEqual(user_with_email("Lovelace@example.org"), ada)

    def test_leaves_out_the_given_user(self):
        ada = make_user("ada@example.org")
        self.assertIsNone(user_with_email("ada@example.org", user=ada))

    def test_returns_none_for_an_unknown_email(self):
        self.assertIsNone(user_with_email("nobody@example.org"))
