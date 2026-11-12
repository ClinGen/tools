"""Houses tests for the ETS's models."""

import uuid
from unittest import mock

from django.test import TestCase

from email_transfer_service.models import EmailTransfer


class EmailTransferModelTest(TestCase):
    def _create(self) -> EmailTransfer:
        return EmailTransfer.objects.create(
            old_email="old@example.com",
            new_email="new@example.com",
        )

    def test_slug_is_t_and_the_start_of_the_uuid(self):
        transfer = self._create()
        self.assertIsInstance(transfer.pk, uuid.UUID)
        self.assertEqual(transfer.slug, f"T{transfer.pk.hex[:8]}")
        self.assertEqual(str(transfer), transfer.slug)

    def test_slug_does_not_change_on_later_saves(self):
        transfer = self._create()
        slug = transfer.slug
        transfer.status = EmailTransfer.Status.FAILED
        transfer.save()
        transfer.refresh_from_db()
        self.assertEqual(transfer.slug, slug)

    def test_colliding_slug_gets_a_new_uuid(self):
        taken = uuid.UUID("3f2a9c1e-0000-4000-8000-000000000001")
        fresh = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000002")
        EmailTransfer.objects.create(
            id=taken, old_email="a@example.com", new_email="b@example.com"
        )
        # Same first 8 hex characters as the taken one, so the slug collides.
        colliding = uuid.UUID("3f2a9c1e-ffff-4fff-8fff-ffffffffffff")
        with mock.patch("common.models.uuid.uuid4", return_value=fresh):
            transfer = EmailTransfer.objects.create(
                id=colliding,
                old_email="old@example.com",
                new_email="new@example.com",
            )
        self.assertEqual(transfer.pk, fresh)
        self.assertEqual(transfer.slug, "Taaaaaaaa")

    def test_changes_are_recorded_in_history(self):
        transfer = self._create()
        transfer.status = EmailTransfer.Status.SUCCEEDED
        transfer.save()
        self.assertEqual(transfer.history.first().status, "succeeded")  # type: ignore
        self.assertGreaterEqual(transfer.history.count(), 2)  # type: ignore
