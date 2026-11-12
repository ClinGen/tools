"""Houses tests for importing data from the old AS."""

import io

from django.core.management import call_command
from django.test import TestCase, override_settings

from affiliations_service.management.commands.import_old_as import (
    ImportResult,
    import_old_as,
)
from affiliations_service.models import (
    CDWG,
    Affiliation,
    ClinVarSubmitterId,
    Membership,
    User,
)

GPM_UUID = "df296795-0043-4bc1-bc12-3a8309e3ebcb"

CDWGS = [
    {"id": 1, "name": "None", "uuid": None},
    {"id": 3, "name": "Cardiovascular", "uuid": None},
    {"id": 18, "name": "Somatic Cancer", "uuid": None},
]

AFFILIATIONS = [
    {
        "affiliation_id": 10016,
        "expert_panel_id": 40016,
        "full_name": "Cardiomyopathy GCEP",
        "short_name": "CM",
        "status": "ACTIVE",
        "type": "GCEP",
        "clinical_domain_working_group": 3,
        "members": "",
        "approvers": [
            {"approver_name": "Ada Lovelace"},
            {"approver_name": "Alan Turing"},
        ],
        "coordinators": [
            {
                "coordinator_name": "Ada Lovelace",
                "coordinator_email": "Ada@Example.org",
            },
            {"coordinator_name": "Grace Hopper", "coordinator_email": ""},
        ],
        "clinvar_submitter_ids": [{"clinvar_submitter_id": "500001"}],
        "is_deleted": False,
        "uuid": GPM_UUID,
    },
    {
        "affiliation_id": 10016,
        "expert_panel_id": 50016,
        "full_name": "Cardiomyopathy VCEP",
        "short_name": None,
        "status": "RETIRED",
        "type": "VCEP",
        "clinical_domain_working_group": 3,
        "members": None,
        "approvers": [],
        "coordinators": [
            {"coordinator_name": "Ada L.", "coordinator_email": "ada@example.org"}
        ],
        "clinvar_submitter_ids": [],
        "is_deleted": True,
        "uuid": None,
    },
    {
        # Breaks a new rule: an SC-VCEP outside the Somatic Cancer CDWG.
        "affiliation_id": 10020,
        "expert_panel_id": 50020,
        "full_name": "Odd SC-VCEP",
        "short_name": "",
        "status": "APPLYING",
        "type": "SC_VCEP",
        "clinical_domain_working_group": 3,
        "members": "",
        "approvers": [],
        "coordinators": [],
        "clinvar_submitter_ids": [],
        "is_deleted": False,
        "uuid": None,
    },
]


def fake_fetch(path: str) -> list[dict]:
    """Returns the old AS's responses without calling it."""
    return {"cdwg_list/": CDWGS, "database_list/": AFFILIATIONS}[path]


class ImportTest(TestCase):
    def _import(self, *, dry_run: bool = False) -> ImportResult:
        return import_old_as(fake_fetch, dry_run=dry_run)

    def test_imports_cdwgs_and_affiliations_with_their_ids(self):
        self._import()
        self.assertEqual(CDWG.objects.count(), 3)
        gcep = Affiliation.objects.get(affiliation_id=10016, type="GCEP")
        self.assertEqual(gcep.expert_panel_id, 40016)
        self.assertEqual(gcep.cdwg.name, "Cardiovascular")
        self.assertEqual(str(gcep.gpm_uuid), GPM_UUID)
        self.assertEqual(gcep.short_name, "CM")
        vcep = Affiliation.objects.get(affiliation_id=10016, type="VCEP")
        self.assertEqual((vcep.expert_panel_id, vcep.status), (50016, "RETIRED"))
        self.assertTrue(vcep.is_deleted)
        self.assertEqual(vcep.short_name, "")

    def test_imports_submitter_ids(self):
        self._import()
        submitter = ClinVarSubmitterId.objects.get()
        self.assertEqual(submitter.submitter_id, "500001")
        self.assertEqual(submitter.affiliation.type, "GCEP")

    def test_coordinators_and_approvers_become_users_and_memberships(self):
        self._import()
        ada = User.objects.get(email__iexact="ada@example.org")
        self.assertEqual(ada.name, "Ada Lovelace")
        self.assertEqual(
            set(ada.memberships.values_list("affiliation__type", "role")),  # type: ignore
            {("GCEP", "COORDINATOR"), ("GCEP", "APPROVER"), ("VCEP", "COORDINATOR")},
        )
        self.assertEqual(User.objects.get(name="Grace Hopper").email, "")
        alan = User.objects.get(name="Alan Turing")
        self.assertEqual(alan.email, "")
        self.assertEqual(alan.memberships.get().role, Membership.Role.APPROVER)  # type: ignore
        self.assertEqual(User.objects.count(), 3)

    def test_a_second_run_creates_nothing_new(self):
        self._import()
        counts = [
            model.objects.count()
            for model in [CDWG, Affiliation, ClinVarSubmitterId, User, Membership]
        ]
        self._import()
        self.assertEqual(
            counts,
            [
                model.objects.count()
                for model in [CDWG, Affiliation, ClinVarSubmitterId, User, Membership]
            ],
        )

    def test_a_second_run_leaves_unchanged_records_alone(self):
        self._import()
        history_count = Affiliation.history.count()  # type: ignore
        result = self._import()
        self.assertEqual(Affiliation.history.count(), history_count)  # type: ignore
        self.assertEqual(result.updated["affiliations"], 0)

    def test_dry_run_saves_nothing(self):
        result = self._import(dry_run=True)
        self.assertEqual(result.created["affiliations"], 3)
        self.assertFalse(Affiliation.objects.exists())
        self.assertFalse(User.objects.exists())

    def test_rule_breaking_records_import_with_a_warning(self):
        result = self._import()
        self.assertTrue(Affiliation.objects.filter(affiliation_id=10020).exists())
        self.assertTrue(
            any(
                "Odd SC-VCEP" in warning and "Somatic Cancer" in warning
                for warning in result.warnings
            )
        )


class CommandTest(TestCase):
    @override_settings(AS_OLD_API_KEY="")
    def test_command_needs_a_key(self):
        stderr = io.StringIO()
        with self.assertRaisesMessage(Exception, "AS_API_KEY"):
            call_command("import_old_as", stderr=stderr)
