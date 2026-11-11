"""Replaces the CSS's batches and records with the sample fixture."""

from typing import Any

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import transaction

from clinvar_submission_service.models import (
    AffiliationSettings,
    Batch,
    BatchRecord,
    Record,
)

FIXTURE = "test_batches.json"


class Command(BaseCommand):
    help = (
        "Deletes the CSS's batches, records, and affiliation settings, then loads the "
        "sample fixture. API keys are kept."
    )

    def handle(self, *_args: object, **options: Any) -> None:  # ruff: ignore[any-type] (Django's signature.)
        """Clears the CSS's data and loads the fixture in one transaction.

        Rows already in the database, such as ones made in the UI, or attempts a
        migration numbered differently from the fixture, would otherwise sit beside
        the fixture's and break its unique constraints.
        """
        with transaction.atomic():
            BatchRecord.objects.all().delete()
            Batch.objects.all().delete()
            Record.objects.all().delete()
            AffiliationSettings.objects.all().delete()
            call_command("loaddata", FIXTURE, verbosity=options["verbosity"])
