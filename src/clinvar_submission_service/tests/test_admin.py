"""Houses tests for the CSS's Django admin pages."""

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from clinvar_submission_service.models import ApiKey, Batch
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


class ApiKeyAdminTest(TestCase):
    def setUp(self):
        self.client.force_login(User.objects.create_superuser(username="admin"))

    def test_adding_a_key_shows_it_once(self):
        response = self.client.post(
            reverse("admin:clinvar_submission_service_apikey_add"),
            {"name": "GCI", "is_active": "on"},
            follow=True,
        )
        api_key = ApiKey.objects.get()
        messages = [str(message) for message in response.context["messages"]]
        raw_key = next(
            word
            for message in messages
            for word in message.split()
            if word.startswith(api_key.prefix)
        )
        self.assertEqual(ApiKey.objects.verify(raw_key), api_key)
        change_url = reverse(
            "admin:clinvar_submission_service_apikey_change", args=[api_key.pk]
        )
        self.assertNotContains(self.client.get(change_url), raw_key)

    def test_list_page_renders(self):
        ApiKey.objects.create_key(name="GCI")
        response = self.client.get(
            reverse("admin:clinvar_submission_service_apikey_changelist")
        )
        self.assertContains(response, "GCI")
