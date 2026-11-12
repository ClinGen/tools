"""Houses tests for the CSS's Django admin pages."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from clinvar_submission_service.models import Batch
from clinvar_submission_service.tests.fakes import make_saved_record


class BatchAdminTest(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser(username="admin"))
        self.batch = Batch.objects.create()

    def test_list_page_renders(self):
        url = reverse("admin:clinvar_submission_service_batch_changelist")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.batch.slug)

    def test_change_page_renders(self):
        url = reverse(
            "admin:clinvar_submission_service_batch_change",
            args=[self.batch.pk],
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_change_page_lists_the_records(self):
        make_saved_record(self.batch, "var-1")
        url = reverse(
            "admin:clinvar_submission_service_batch_change",
            args=[self.batch.pk],
        )
        response = self.client.get(url)
        self.assertContains(
            response, "NC_000017.11:g.43045712T&gt;C: Likely pathogenic"
        )

    def test_a_records_page_lists_its_batches(self):
        record = make_saved_record(self.batch, "var-1")
        url = reverse(
            "admin:clinvar_submission_service_record_change", args=[record.pk]
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.batch.slug)
