"""Imports CDWGs, affiliations, and users from the old AS's API.

The old AS (affils.clinicalgenome.org) keeps coordinators as a name and an email and
approvers as a name only. Each becomes a `User` with a membership in the affiliation.
Users are matched by email, ignoring case, and then by name, so an approver who is
also a coordinator becomes one user. Running the import again updates what it
imported before instead of duplicating it.

Records are saved as the old AS has them, even when they break the AS's rules, so
nothing is lost. Each broken rule is reported as a warning for staff to fix.

Run it with `uv run src/manage.py import_old_as`. It reads the old AS's API with the key
in AS_API_KEY. Add --dry-run to see what it would do without saving anything.
"""

import json
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import IntegrityError, transaction

from affiliations_service.models import (
    CDWG,
    Affiliation,
    ClinVarSubmitterId,
    Membership,
    User,
)

# The old AS answers each path this import reads with a list of JSON objects.
Fetch = Callable[[str], list[dict]]

# How long to wait for the old AS to answer, in seconds.
TIMEOUT = 60


@dataclass
class ImportResult:
    """What an import did.

    Attributes:
        created: How many of each kind of record were created.
        updated: How many existing records were updated.
        warnings: Problems with records that were imported anyway, or skipped.
    """

    created: Counter = field(default_factory=Counter)
    updated: Counter = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)


def make_fetch(base_url: str, api_key: str) -> Fetch:
    """Returns a function that GETs a path from the old AS's API and decodes the JSON.

    Args:
        base_url: The API's base URL, ending in a slash.
        api_key: An old AS API key, sent in the X-Api-Key header.

    Returns:
        A function that takes a path, such as "cdwg_list/", and returns its JSON.
    """

    def fetch(path: str) -> list[dict]:
        request = urllib.request.Request(  # ruff: ignore[suspicious-url-open-usage] (The URL comes from settings.)
            base_url + path,
            headers={"X-Api-Key": api_key, "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # ruff: ignore[suspicious-url-open-usage] (The URL comes from settings.)
            return json.load(response)

    return fetch


class _Importer:
    """Holds one import's state: what it found, made, and warned about."""

    def __init__(self, fetch: Fetch) -> None:
        self.fetch = fetch
        self.result = ImportResult()
        self.cdwgs_by_old_id: dict[int, CDWG] = {}

    def run(self) -> None:
        for old in self.fetch("cdwg_list/"):
            self.cdwgs_by_old_id[old["id"]] = self._import_cdwg(old)
        imported = []
        for old in self.fetch("database_list/"):
            affiliation = self._import_affiliation(old)
            if affiliation is not None:
                imported.append((old, affiliation))
        # Coordinators go first, since they have emails; approvers are then matched
        # to them by name.
        for old, affiliation in imported:
            for coordinator in old.get("coordinators") or []:
                user = self._find_or_create_user(
                    coordinator["coordinator_name"], coordinator["coordinator_email"]
                )
                self._add_membership(user, affiliation, Membership.Role.COORDINATOR)
        for old, affiliation in imported:
            for approver in old.get("approvers") or []:
                user = self._find_or_create_user(approver["approver_name"], "")
                self._add_membership(user, affiliation, Membership.Role.APPROVER)

    def _import_cdwg(self, old: dict) -> CDWG:
        name = old["name"].strip()
        cdwg = CDWG.objects.filter(name__iexact=name).first()
        if cdwg is None:
            self.result.created["cdwgs"] += 1
            return CDWG.objects.create(name=name, gpm_uuid=old.get("uuid") or None)
        if old.get("uuid") and str(cdwg.gpm_uuid) != old["uuid"]:
            cdwg.gpm_uuid = old["uuid"]
            cdwg.save()
            self.result.updated["cdwgs"] += 1
        return cdwg

    def _import_affiliation(self, old: dict) -> Affiliation | None:
        label = f"{old['full_name']} ({old['affiliation_id']}, {old['type']})"
        cdwg = self.cdwgs_by_old_id.get(old["clinical_domain_working_group"])
        if cdwg is None:
            self.result.warnings.append(
                f"Skipped {label}: its CDWG isn't in the old AS."
            )
            return None
        affiliation = Affiliation.objects.filter(
            affiliation_id=old["affiliation_id"], type=old["type"]
        ).first()
        is_new = affiliation is None
        affiliation = affiliation or Affiliation(
            affiliation_id=old["affiliation_id"], type=old["type"]
        )
        changes = {
            "expert_panel_id": old["expert_panel_id"],
            "full_name": old["full_name"],
            "short_name": old.get("short_name") or "",
            "status": old["status"],
            "cdwg_id": cdwg.pk,
            "gpm_uuid": old.get("uuid") or None,
            "is_deleted": old.get("is_deleted", False),
        }
        changed = is_new or any(
            str(getattr(affiliation, name)) != str(value)
            for name, value in changes.items()
        )
        for name, value in changes.items():
            setattr(affiliation, name, value)
        self._warn_about_rules(affiliation, label)
        try:
            with transaction.atomic():
                # Saving only changed affiliations keeps reruns out of their history.
                if changed:
                    affiliation.save()
                for submitter in old.get("clinvar_submitter_ids") or []:
                    ClinVarSubmitterId.objects.get_or_create(
                        affiliation=affiliation,
                        submitter_id=submitter["clinvar_submitter_id"],
                    )
        except IntegrityError as error:
            self.result.warnings.append(f"Skipped {label}: {error}")
            return None
        if is_new:
            self.result.created["affiliations"] += 1
        elif changed:
            self.result.updated["affiliations"] += 1
        return affiliation

    def _warn_about_rules(self, affiliation: Affiliation, label: str) -> None:
        """Adds a warning for each AS rule the affiliation breaks."""
        try:
            affiliation.clean()
        except ValidationError as error:
            for message in error.messages:
                self.result.warnings.append(f"{label} breaks a rule: {message}")

    def _find_or_create_user(self, name: str, email: str) -> User:
        name, email = name.strip(), email.strip()
        user = None
        if email:
            user = (
                User.objects.filter(email__iexact=email).first()
                or User.objects.filter(other_emails__email__iexact=email).first()
            )
        if user is None:
            same_name = User.objects.filter(name__iexact=name)
            if email:
                # Only a user without an email can be the same as one with an email.
                same_name = same_name.filter(email="")
            user = same_name.first()
            if user is not None and email:
                user.email = email
                user.save()
        if user is None:
            user = User.objects.create(name=name, email=email)
            self.result.created["users"] += 1
        return user

    def _add_membership(self, user: User, affiliation: Affiliation, role: str) -> None:
        current = Membership.objects.filter(
            user=user,
            affiliation=affiliation,
            role=role,
            end_date__isnull=True,
        )
        if not current.exists():
            Membership.objects.create(user=user, affiliation=affiliation, role=role)
            self.result.created["memberships"] += 1


def import_old_as(fetch: Fetch, *, dry_run: bool = False) -> ImportResult:
    """Imports CDWGs, affiliations, and users from the old AS.

    Args:
        fetch: Returns the JSON at a path of the old AS's API. `make_fetch` builds one.
        dry_run: Whether to undo everything at the end, to see what would happen.

    Returns:
        What was created and updated, and any warnings.
    """
    importer = _Importer(fetch)
    with transaction.atomic():
        importer.run()
        if dry_run:
            transaction.set_rollback(True)
    return importer.result


class Command(BaseCommand):
    help = "Imports CDWGs, affiliations, and users from the old AS's API."

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
        for kind in ["cdwgs", "affiliations", "users", "memberships"]:
            self.stdout.write(
                f"{kind}: {result.created[kind]} created, "
                f"{result.updated[kind]} updated"
            )
        if options["dry_run"]:
            self.stdout.write("Dry run: nothing was saved.")
