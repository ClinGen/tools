"""Houses tests for the CSS's data migrations."""

import importlib
from typing import ClassVar

from django.apps import apps
from django.db import models
from django.test import TestCase

from clinvar_submission_service.models import Batch


class _RenamedModels:
    """Stands in for a migration's apps, giving today's models their old names.

    The status migration ran when Batch was called Submission.
    """

    OLD_NAMES: ClassVar[dict[str, str]] = {
        "Submission": "Batch",
        "HistoricalSubmission": "HistoricalBatch",
    }

    def get_model(self, app_label: str, model_name: str) -> type[models.Model]:
        """Returns today's model for the model's old name."""
        return apps.get_model(app_label, self.OLD_NAMES.get(model_name, model_name))


class StatusMigrationTest(TestCase):
    """The migration that names each status relative to ClinVar."""

    migration = importlib.import_module(
        "clinvar_submission_service.migrations.0005_status_relative_to_clinvar"
    )

    def _set_raw_status(self, batch: Batch, status: str) -> None:
        """Gives the batch and its history a status as an old row had it."""
        Batch.objects.filter(pk=batch.pk).update(status=status)
        batch.history.update(status=status)  # type: ignore

    def test_renames_every_old_status_and_back(self):
        for old, new in self.migration.RENAMES.items():
            with self.subTest(old=old):
                batch = Batch.objects.create()
                self._set_raw_status(batch, old)
                self.migration.rename_statuses(_RenamedModels(), None)
                batch.refresh_from_db()
                self.assertEqual(batch.status, new)
                history = batch.history.values_list("status", flat=True)  # type: ignore
                self.assertEqual(set(history), {new})
                self.migration.restore_statuses(_RenamedModels(), None)
                batch.refresh_from_db()
                self.assertEqual(batch.status, old)

    def test_renames_to_the_current_statuses(self):
        self.assertEqual(set(self.migration.RENAMES.values()), set(Batch.Status.values))
