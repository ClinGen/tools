"""Houses tests for memberships."""

import datetime

from django.contrib.auth.models import User as StaffUser
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from affiliations_service.models import Affiliation, Membership, User
from affiliations_service.test_models import make_affiliation
from affiliations_service.test_rules import errors_for
from affiliations_service.test_users import make_user

TODAY = timezone.localdate()
YESTERDAY = TODAY - datetime.timedelta(days=1)
TOMORROW = TODAY + datetime.timedelta(days=1)


def make_membership(
    user: User,
    affiliation: Affiliation,
    role: str = Membership.Role.CURATOR,
    **fields: object,
) -> Membership:
    """Returns a new membership."""
    return Membership.objects.create(
        user=user, affiliation=affiliation, role=role, **fields
    )


class MembershipTest(TestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.user = make_user()
        cls.affiliation = make_affiliation()

    def test_a_user_can_hold_two_roles_in_one_affiliation(self):
        make_membership(self.user, self.affiliation, Membership.Role.COORDINATOR)
        make_membership(self.user, self.affiliation, Membership.Role.APPROVER)
        self.assertEqual(self.affiliation.memberships.count(), 2)  # type: ignore

    def test_a_second_open_membership_in_the_same_role_raises(self):
        make_membership(self.user, self.affiliation)
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_membership(self.user, self.affiliation)

    def test_the_same_role_again_after_an_ended_one_is_fine(self):
        make_membership(self.user, self.affiliation, end_date=YESTERDAY)
        make_membership(self.user, self.affiliation)
        self.assertEqual(self.affiliation.memberships.count(), 2)  # type: ignore

    def test_duplicate_open_role_has_a_plain_error(self):
        make_membership(self.user, self.affiliation)
        duplicate = Membership(
            user=self.user,
            affiliation=self.affiliation,
            role=Membership.Role.CURATOR,
        )
        self.assertIn(
            "This user already holds this role in this affiliation.",
            str(errors_for(duplicate)),
        )

    def test_end_date_before_start_date_raises(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            make_membership(
                self.user, self.affiliation, start_date=TODAY, end_date=YESTERDAY
            )
        backwards = Membership(
            user=self.user,
            affiliation=self.affiliation,
            role=Membership.Role.CURATOR,
            start_date=TODAY,
            end_date=YESTERDAY,
        )
        self.assertIn(
            "The end date can't be before the start date.", str(errors_for(backwards))
        )

    def test_current_includes_open_and_future_ended_memberships(self):
        open_ = make_membership(self.user, self.affiliation, Membership.Role.CURATOR)
        future = make_membership(
            self.user, self.affiliation, Membership.Role.APPROVER, end_date=TOMORROW
        )
        make_membership(
            self.user,
            self.affiliation,
            Membership.Role.COORDINATOR,
            end_date=YESTERDAY,
        )
        make_membership(
            self.user, self.affiliation, Membership.Role.COORDINATOR, end_date=TODAY
        )
        self.assertQuerySetEqual(
            Membership.objects.current(), [open_, future], ordered=False
        )

    def test_ending_a_membership_keeps_it(self):
        membership = make_membership(self.user, self.affiliation)
        membership.end()
        membership.refresh_from_db()
        self.assertEqual(membership.end_date, TODAY)
        self.assertFalse(membership.is_current)
        self.assertEqual(Membership.objects.count(), 1)

    def test_ending_on_a_given_date(self):
        membership = make_membership(self.user, self.affiliation)
        membership.end(TOMORROW)
        self.assertEqual(membership.end_date, TOMORROW)
        self.assertTrue(membership.is_current)

    def test_changes_record_history(self):
        membership = make_membership(self.user, self.affiliation)
        membership.end()
        self.assertEqual(membership.history.count(), 2)  # type: ignore


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
