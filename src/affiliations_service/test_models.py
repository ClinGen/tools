"""Houses tests for the AS's models."""

from django.db import IntegrityError, transaction
from django.test import TestCase

from affiliations_service.models import CDWG, Affiliation, ClinVarSubmitterId


def make_cdwg(name: str = "Cardiovascular") -> CDWG:
    """Returns a new CDWG with the given name."""
    return CDWG.objects.create(name=name)


def make_affiliation(
    type_: str = Affiliation.Type.VCEP,
    *,
    cdwg: CDWG | None = None,
    **fields: object,
) -> Affiliation:
    """Returns a new affiliation of the given type.

    Args:
        type_: The affiliation's type.
        cdwg: The affiliation's CDWG. A new one is made if this is None.
        **fields: Any other fields to set.

    Returns:
        The saved affiliation.
    """
    if cdwg is None:
        cdwg = CDWG.objects.first() or make_cdwg()
    fields.setdefault("full_name", "Test Expert Panel")
    return Affiliation.objects.create(type=type_, cdwg=cdwg, **fields)


class AffiliationIdTest(TestCase):
    def test_first_affiliation_gets_10000(self):
        self.assertEqual(make_affiliation().affiliation_id, 10000)

    def test_next_affiliation_gets_the_max_plus_one(self):
        make_affiliation(affiliation_id=10041)
        make_affiliation()
        self.assertEqual(make_affiliation().affiliation_id, 10043)

    def test_deleted_affiliations_still_count(self):
        make_affiliation().delete()
        self.assertEqual(make_affiliation().affiliation_id, 10001)

    def test_reaching_20000_raises(self):
        make_affiliation(affiliation_id=19999)
        with self.assertRaises(ValueError):
            make_affiliation()


class ExpertPanelIdTest(TestCase):
    def test_gcep_gets_the_40000_range(self):
        affiliation = make_affiliation(Affiliation.Type.GCEP, affiliation_id=10042)
        self.assertEqual(affiliation.expert_panel_id, 40042)

    def test_vcep_and_sc_vcep_get_the_50000_range(self):
        for offset, type_ in enumerate(
            [Affiliation.Type.VCEP, Affiliation.Type.SC_VCEP]
        ):
            with self.subTest(type=type_):
                affiliation = make_affiliation(type_, affiliation_id=10042 + offset)
                self.assertEqual(affiliation.expert_panel_id, 50042 + offset)

    def test_independent_curation_group_gets_none(self):
        affiliation = make_affiliation(Affiliation.Type.INDEPENDENT_CURATION)
        self.assertIsNone(affiliation.expert_panel_id)

    def test_expert_panel_id_doesnt_change_on_later_saves(self):
        affiliation = make_affiliation(Affiliation.Type.GCEP)
        affiliation.full_name = "Renamed"
        affiliation.save()
        affiliation.refresh_from_db()
        self.assertEqual(affiliation.expert_panel_id, 40000)


class SoftDeleteTest(TestCase):
    def test_delete_marks_the_affiliation_deleted(self):
        affiliation = make_affiliation()
        affiliation.delete()
        affiliation.refresh_from_db()
        self.assertTrue(affiliation.is_deleted)

    def test_queryset_delete_marks_affiliations_deleted(self):
        make_affiliation()
        make_affiliation()
        Affiliation.objects.all().delete()
        self.assertEqual(Affiliation.objects.filter(is_deleted=True).count(), 2)

    def test_active_excludes_deleted_affiliations(self):
        kept = make_affiliation()
        make_affiliation().delete()
        self.assertQuerySetEqual(Affiliation.objects.active(), [kept])


class UniquenessTest(TestCase):
    def _assert_integrity_error(self, create: object) -> None:
        with self.assertRaises(IntegrityError), transaction.atomic():
            create()  # type: ignore

    def test_vcep_and_gcep_may_share_an_affiliation_id(self):
        make_affiliation(Affiliation.Type.VCEP, affiliation_id=10005)
        gcep = make_affiliation(Affiliation.Type.GCEP, affiliation_id=10005)
        self.assertEqual(gcep.expert_panel_id, 40005)

    def test_affiliation_id_is_unique_per_type(self):
        make_affiliation(affiliation_id=10005)
        self._assert_integrity_error(lambda: make_affiliation(affiliation_id=10005))

    def test_expert_panel_id_is_unique(self):
        make_affiliation(Affiliation.Type.GCEP, affiliation_id=10005)
        self._assert_integrity_error(
            lambda: make_affiliation(
                Affiliation.Type.VCEP, affiliation_id=10006, expert_panel_id=40005
            )
        )

    def test_gpm_uuids_are_unique(self):
        gpm_uuid = "6a1b5f0e-8f0c-4d7e-9a43-2b0f5d3c1e9a"
        make_affiliation(gpm_uuid=gpm_uuid)
        CDWG.objects.create(name="Hearing Loss", gpm_uuid=gpm_uuid)
        self._assert_integrity_error(lambda: make_affiliation(gpm_uuid=gpm_uuid))
        self._assert_integrity_error(
            lambda: CDWG.objects.create(name="Kidney", gpm_uuid=gpm_uuid)
        )

    def test_cdwg_names_are_unique_ignoring_case(self):
        make_cdwg("Hearing Loss")
        self._assert_integrity_error(lambda: make_cdwg("hearing loss"))

    def test_submitter_ids_are_unique_per_affiliation(self):
        affiliation = make_affiliation()
        ClinVarSubmitterId.objects.create(
            affiliation=affiliation, submitter_id="500001"
        )
        self._assert_integrity_error(
            lambda: ClinVarSubmitterId.objects.create(
                affiliation=affiliation, submitter_id="500001"
            )
        )


class HistoryTest(TestCase):
    def test_saving_records_history(self):
        affiliation = make_affiliation()
        affiliation.status = Affiliation.Status.ACTIVE
        affiliation.save()
        self.assertEqual(affiliation.history.count(), 2)  # type: ignore
        self.assertEqual(affiliation.cdwg.history.count(), 1)

    def test_soft_delete_records_history(self):
        affiliation = make_affiliation()
        affiliation.delete()
        self.assertTrue(affiliation.history.first().is_deleted)  # type: ignore
