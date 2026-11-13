"""Houses tests for the AS API's user endpoints."""

import uuid

from affiliations_service.models import User, UserEmail
from affiliations_service.tests.test_api_cdwgs import ApiTestCase
from affiliations_service.tests.test_users import make_user

URL = "/as/api/v1/users"
GPM_UUID = "6a1b5f0e-8f0c-4d7e-9a43-2b0f5d3c1e9a"
ORCID = "0000-0002-1825-0097"


class UserListTest(ApiTestCase):
    @classmethod
    def setUpTestData(cls) -> None:
        cls.ada = make_user(
            "ada@example.org", name="Ada Lovelace", orcid=ORCID, gpm_uuid=GPM_UUID
        )
        UserEmail.objects.create(user=cls.ada, email="countess@uni.edu")
        UserEmail.objects.create(user=cls.ada, email="ada@uni.edu")
        cls.grace = make_user("grace@example.org", name="Grace Hopper")

    def _names(self, **params: str | int) -> list[str]:
        return [item["name"] for item in self.get(URL, **params).json()["items"]]

    def test_lists_users_by_name(self):
        self.assertEqual(self._names(), ["Ada Lovelace", "Grace Hopper"])

    def test_q_finds_users_by_name_and_any_email(self):
        self.assertEqual(self._names(q="hopper"), ["Grace Hopper"])
        self.assertEqual(self._names(q="countess"), ["Ada Lovelace"])
        self.assertEqual(self._names(q="uni.edu"), ["Ada Lovelace"])

    def test_email_filter_matches_primary_and_other_emails_in_any_case(self):
        self.assertEqual(self._names(email="GRACE@example.org"), ["Grace Hopper"])
        self.assertEqual(self._names(email="Countess@Uni.edu"), ["Ada Lovelace"])
        self.assertEqual(self._names(email="uni.edu"), [])

    def test_orcid_and_gpm_uuid_filters(self):
        self.assertEqual(self._names(orcid=ORCID), ["Ada Lovelace"])
        self.assertEqual(self._names(gpm_uuid=GPM_UUID), ["Ada Lovelace"])

    def test_items_include_other_emails(self):
        item = self.get(URL, email="ada@example.org").json()["items"][0]
        self.assertEqual(item["other_emails"], ["ada@uni.edu", "countess@uni.edu"])
        self.assertEqual(item["id"], str(self.ada.pk))


class UserCreateUpdateTest(ApiTestCase):
    def test_create(self):
        response = self.post(
            URL,
            {
                "name": "Ada Lovelace",
                "email": "ada@example.org",
                "orcid": ORCID,
                "credentials": "PhD",
                "other_emails": ["ada@uni.edu"],
            },
        )
        self.assertEqual(response.status_code, 201)
        user = User.objects.get()
        self.assertEqual(user.credentials, "PhD")
        self.assertEqual(response.json()["other_emails"], ["ada@uni.edu"])

    def test_create_without_an_email(self):
        response = self.post(URL, {"name": "Approver Only"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["email"], "")

    def test_update_replaces_other_emails(self):
        ada = make_user()
        UserEmail.objects.create(user=ada, email="old@uni.edu")
        response = self.patch(
            f"{URL}/{ada.pk}",
            {"institution": "Stanford University", "other_emails": ["new@uni.edu"]},
        )
        self.assertEqual(response.status_code, 200)
        ada.refresh_from_db()
        self.assertEqual(ada.institution, "Stanford University")
        emails = ada.other_emails.values_list("email", flat=True)  # type: ignore
        self.assertEqual(list(emails), ["new@uni.edu"])

    def test_update_without_other_emails_keeps_them(self):
        ada = make_user()
        UserEmail.objects.create(user=ada, email="old@uni.edu")
        self.patch(f"{URL}/{ada.pk}", {"name": "Augusta Ada King"})
        self.assertEqual(ada.other_emails.count(), 1)  # type: ignore

    def test_duplicate_emails_return_400_with_the_other_users_id(self):
        ada = make_user("ada@example.org")
        grace = make_user("grace@example.org", name="Grace Hopper")
        UserEmail.objects.create(user=grace, email="g@uni.edu")
        cases = [
            ({"name": "Imposter", "email": "ADA@example.org"}, ada),
            ({"name": "Imposter", "email": "g@UNI.edu"}, grace),
            (
                {
                    "name": "Imposter",
                    "email": "new@example.org",
                    "other_emails": ["ada@example.org"],
                },
                ada,
            ),
        ]
        for body, owner in cases:
            with self.subTest(body=body):
                response = self.post(URL, body)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(
                    response.json(),
                    {
                        "detail": f"The user with AS ID {owner.pk} already has this "
                        "email.",
                        "existing_user_id": str(owner.pk),
                    },
                )
        self.assertEqual(User.objects.count(), 2)

    def test_patching_in_a_taken_email_returns_400_with_the_other_users_id(self):
        ada = make_user("ada@example.org")
        grace = make_user("grace@example.org", name="Grace Hopper")
        response = self.patch(f"{URL}/{grace.pk}", {"email": "ada@example.org"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["existing_user_id"], str(ada.pk))

    def test_bad_orcid_returns_400(self):
        response = self.post(
            URL, {"name": "Ada", "email": "a@example.org", "orcid": "123"}
        )
        self.assertEqual(response.status_code, 400)

    def test_unknown_ids_return_404(self):
        unknown = f"{URL}/{uuid.uuid4()}"
        self.assertEqual(self.get(unknown).status_code, 404)
        self.assertEqual(self.patch(unknown, {"name": "X"}).status_code, 404)

    def test_deleting_a_user_removes_them(self):
        ada = make_user()
        self.assertEqual(self.delete(f"{URL}/{ada.pk}").status_code, 204)
        self.assertFalse(User.objects.filter(pk=ada.pk).exists())

    def test_requests_without_a_key_get_401(self):
        self.assertEqual(self.client.get(URL).status_code, 401)


class SimilarNameTest(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.jane = make_user(
            "jane@example.org", name="Jane Smith", preferred_name="Janie"
        )

    def test_a_similar_name_returns_409_with_the_matches(self):
        response = self.post(URL, {"name": "Smith, Jane", "email": "js@uni.edu"})
        self.assertEqual(response.status_code, 409)
        body = response.json()
        self.assertIn("allow_similar_name", body["detail"])
        self.assertEqual(
            body["possible_duplicates"],
            [
                {
                    "id": str(self.jane.pk),
                    "name": "Jane Smith",
                    "preferred_name": "Janie",
                    "email": "jane@example.org",
                }
            ],
        )
        self.assertEqual(User.objects.count(), 1)

    def test_allow_similar_name_creates_the_user(self):
        response = self.post(
            URL,
            {"name": "Smith, Jane", "email": "js@uni.edu", "allow_similar_name": True},
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(User.objects.count(), 2)
        self.assertNotIn("allow_similar_name", response.json())

    def test_a_distinct_name_creates_the_user(self):
        response = self.post(URL, {"name": "Grace Hopper"})
        self.assertEqual(response.status_code, 201)

    def test_patching_in_a_similar_name_succeeds(self):
        grace = make_user("grace@example.org", name="Grace Hopper")
        response = self.patch(f"{URL}/{grace.pk}", {"name": "Jane Smyth"})
        self.assertEqual(response.status_code, 200)
        grace.refresh_from_db()
        self.assertEqual(grace.name, "Jane Smyth")
