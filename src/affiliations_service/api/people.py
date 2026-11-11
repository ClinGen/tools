"""Serves the AS API's person endpoints."""

import uuid
from datetime import datetime

from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Schema, Status
from ninja.pagination import paginate
from pydantic import ConfigDict

from affiliations_service.api.helpers import save_validated
from affiliations_service.api.memberships import MembershipOut
from affiliations_service.models import Membership, Person, PersonEmail

router = Router()


class PersonOut(Schema):
    """A person, with their other emails."""

    id: uuid.UUID
    name: str
    preferred_name: str
    email: str
    other_emails: list[str]
    institution: str
    orcid: str
    credentials: str
    gpm_uuid: uuid.UUID | None
    added_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_other_emails(person: Person) -> list[str]:
        """Returns the person's other emails as strings."""
        return [item.email for item in person.other_emails.all()]  # ty: ignore[unresolved-attribute] (Django adds the reverse relation.)


class PersonDetail(PersonOut):
    """A person, with their current memberships."""

    current_memberships: list[MembershipOut]

    @staticmethod
    def resolve_current_memberships(person: Person) -> list[Membership]:
        """Returns the memberships that haven't ended."""
        return list(person.memberships.current())  # ty: ignore[unresolved-attribute] (Django adds the reverse relation.)


class PersonIn(Schema):
    """The fields for a new person."""

    model_config = ConfigDict(extra="forbid")

    name: str
    email: str
    preferred_name: str = ""
    institution: str = ""
    orcid: str = ""
    credentials: str = ""
    gpm_uuid: uuid.UUID | None = None
    other_emails: list[str] = []


class PersonPatch(Schema):
    """The fields to change on a person. Leave out the ones that don't change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    email: str | None = None
    preferred_name: str | None = None
    institution: str | None = None
    orcid: str | None = None
    credentials: str | None = None
    gpm_uuid: uuid.UUID | None = None
    other_emails: list[str] | None = None


class PersonFilters(Schema):
    """Narrows the list of people."""

    q: str | None = None
    email: str | None = None
    orcid: str | None = None
    gpm_uuid: uuid.UUID | None = None


def _people() -> QuerySet[Person]:
    return Person.objects.prefetch_related("other_emails")


def _save(person: Person, changes: dict, other_emails: list[str] | None) -> None:
    """Saves a person and, if given, replaces their other emails.

    Each other email is checked like the person, so a taken email is a 400.
    """
    with transaction.atomic():
        save_validated(person, changes)
        if other_emails is not None:
            person.other_emails.all().delete()  # ty: ignore[unresolved-attribute] (Django adds the reverse relation.)
            unique_emails = {email.lower(): email for email in other_emails}.values()
            for email in unique_emails:
                save_validated(PersonEmail(person=person, email=email))


@router.get("", response=list[PersonOut])
@paginate
def list_people(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    filters: Query[PersonFilters],
) -> QuerySet[Person]:
    """Lists people by name.

    `q` searches names and every email. `email` matches a primary or other email
    exactly, ignoring case.

    Returns:
        The matching people.
    """
    people = _people()
    if filters.q:
        people = people.filter(
            Q(name__icontains=filters.q)
            | Q(preferred_name__icontains=filters.q)
            | Q(email__icontains=filters.q)
            | Q(other_emails__email__icontains=filters.q)
        )
    if filters.email:
        people = people.filter(
            Q(email__iexact=filters.email)
            | Q(other_emails__email__iexact=filters.email)
        )
    if filters.orcid:
        people = people.filter(orcid=filters.orcid)
    if filters.gpm_uuid:
        people = people.filter(gpm_uuid=filters.gpm_uuid)
    return people.distinct()


@router.get("/{person_id}", response=PersonDetail)
def get_person(request: HttpRequest, person_id: uuid.UUID) -> Person:  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    """Gets one person.

    Returns:
        The person.
    """
    return get_object_or_404(_people(), pk=person_id)


@router.post("", response={201: PersonDetail})
def create_person(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    data: PersonIn,
) -> Status[Person]:
    """Creates a person. No two people share an email, ignoring case.

    Returns:
        201 and the new person.
    """
    changes = data.dict()
    other_emails = changes.pop("other_emails")
    person = Person()
    _save(person, changes, other_emails)
    return Status(201, get_object_or_404(_people(), pk=person.pk))


@router.patch("/{person_id}", response=PersonDetail)
def update_person(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    person_id: uuid.UUID,
    data: PersonPatch,
) -> Person:
    """Changes a person. Sending other_emails replaces the list.

    Returns:
        The changed person.
    """
    person = get_object_or_404(Person, pk=person_id)
    changes = data.dict(exclude_unset=True)
    other_emails = changes.pop("other_emails", None)
    _save(person, changes, other_emails)
    return get_object_or_404(_people(), pk=person.pk)
