import hashlib

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.urls import reverse

from clinvar_submission_service.api_auth import API_KEY_HEADER, ApiKeyAuth
from clinvar_submission_service.models import ApiKey


class ApiKeyTest(TestCase):
    def test_stores_only_a_hash_of_the_key(self):
        api_key, raw_key = ApiKey.objects.create_key(name="GCI")
        self.assertEqual(api_key.key_hash, hashlib.sha256(raw_key.encode()).hexdigest())
        self.assertNotIn(
            raw_key, [str(value) for value in ApiKey.objects.values().get().values()]
        )
        self.assertEqual(api_key.prefix, raw_key[:8])

    def test_each_key_is_different(self):
        _, first = ApiKey.objects.create_key(name="GCI")
        _, second = ApiKey.objects.create_key(name="VCI")
        self.assertNotEqual(first, second)

    def test_verifies_an_active_key_and_records_its_use(self):
        api_key, raw_key = ApiKey.objects.create_key(name="GCI")
        self.assertIsNone(api_key.last_used_at)
        self.assertEqual(ApiKey.objects.verify(raw_key), api_key)
        api_key.refresh_from_db()
        self.assertIsNotNone(api_key.last_used_at)

    def test_rejects_an_unknown_or_inactive_key(self):
        api_key, raw_key = ApiKey.objects.create_key(name="GCI")
        self.assertIsNone(ApiKey.objects.verify("not-a-key"))
        self.assertIsNone(ApiKey.objects.verify(""))
        api_key.is_active = False
        api_key.save()
        self.assertIsNone(ApiKey.objects.verify(raw_key))

    def test_string_representation_names_the_client_and_prefix(self):
        api_key, _ = ApiKey.objects.create_key(name="GCI")
        self.assertEqual(str(api_key), f"GCI ({api_key.prefix}…)")


class ApiKeyAuthTest(TestCase):
    def setUp(self):
        self.auth = ApiKeyAuth()
        self.factory = RequestFactory()

    def test_accepts_an_active_key_in_the_header(self):
        api_key, raw_key = ApiKey.objects.create_key(name="GCI")
        request = self.factory.get("/", headers={API_KEY_HEADER: raw_key})
        self.assertEqual(self.auth(request), api_key)

    def test_rejects_a_missing_unknown_or_inactive_key(self):
        api_key, raw_key = ApiKey.objects.create_key(name="GCI")
        api_key.is_active = False
        api_key.save()
        for headers in ({}, {API_KEY_HEADER: "nope"}, {API_KEY_HEADER: raw_key}):
            with self.subTest(headers=headers):
                self.assertIsNone(self.auth(self.factory.get("/", headers=headers)))


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
