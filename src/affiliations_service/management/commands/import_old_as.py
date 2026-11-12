"""Imports CDWGs, affiliations, and people from the old AS.

Run it with `uv run src/manage.py import_old_as`. It reads the old AS's API with the key
in AS_API_KEY. Add --dry-run to see what it would do without saving anything.
"""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError, CommandParser

from affiliations_service.old_as_import import import_old_as, make_fetch


class Command(BaseCommand):
    help = "Imports CDWGs, affiliations, and people from the old AS's API."

    def add_arguments(self, parser: CommandParser) -> None:
        """Adds --dry-run."""
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what the import would do, then undo it.",
        )

    def handle(self, *_args: object, **options: object) -> None:
        """Runs the import and prints what it did.

        Raises:
            CommandError: If AS_API_KEY isn't set.
        """
        if not settings.AS_OLD_API_KEY:
            error_message = "Set AS_API_KEY in .env to an old AS API key."
            raise CommandError(error_message)
        fetch = make_fetch(settings.AS_OLD_API_URL, settings.AS_OLD_API_KEY)
        result = import_old_as(fetch, dry_run=bool(options["dry_run"]))
        for warning in result.warnings:
            self.stderr.write(self.style.WARNING(warning))
        for kind in ["cdwgs", "affiliations", "people", "memberships"]:
            self.stdout.write(
                f"{kind}: {result.created[kind]} created, "
                f"{result.updated[kind]} updated"
            )
        if options["dry_run"]:
            self.stdout.write("Dry run: nothing was saved.")
