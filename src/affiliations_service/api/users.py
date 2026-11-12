"""Serves the AS API's user endpoints."""

import uuid
from datetime import datetime

from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import P, Query, Router, Schema, Status
from ninja.pagination import paginate
from ninja.params import PathEx
from pydantic import ConfigDict

from affiliations_service.api.helpers import save_validated
from affiliations_service.api.memberships import MembershipOut
from affiliations_service.models import Membership, User, UserEmail

router = Router()


class UserOut(Schema):
    """A user, with their other emails."""

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
    def resolve_other_emails(user: User) -> list[str]:
        """Returns the user's other emails as strings."""
        return [item.email for item in user.other_emails.all()]  # ty: ignore[unresolved-attribute] (Django adds the reverse relation.)


class UserDetail(UserOut):
    """A user, with their current memberships."""

    current_memberships: list[MembershipOut]

    @staticmethod
    def resolve_current_memberships(user: User) -> list[Membership]:
        """Returns the memberships that haven't ended."""
        return list(user.memberships.current())  # ty: ignore[unresolved-attribute] (Django adds the reverse relation.)


class UserIn(Schema):
    """The fields for a new user."""

    model_config = ConfigDict(extra="forbid")

    name: str
    email: str = ""
    preferred_name: str = ""
    institution: str = ""
    orcid: str = ""
    credentials: str = ""
    gpm_uuid: uuid.UUID | None = None
    other_emails: list[str] = []


class UserPatch(Schema):
    """The fields to change on a user. Leave out the ones that don't change."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    email: str | None = None
    preferred_name: str | None = None
    institution: str | None = None
    orcid: str | None = None
    credentials: str | None = None
    gpm_uuid: uuid.UUID | None = None
    other_emails: list[str] | None = None


class UserFilters(Schema):
    """Narrows the list of users."""

    q: str | None = None
    email: str | None = None
    orcid: str | None = None
    gpm_uuid: uuid.UUID | None = None


def _users() -> QuerySet[User]:
    return User.objects.prefetch_related("other_emails")


def _save(user: User, changes: dict, other_emails: list[str] | None) -> None:
    """Saves a user and, if given, replaces their other emails.

    Each other email is checked like the user, so a taken email is a 400.
    """
    with transaction.atomic():
        save_validated(user, changes)
        if other_emails is not None:
            user.other_emails.all().delete()  # ty: ignore[unresolved-attribute] (Django adds the reverse relation.)
            unique_emails = {email.lower(): email for email in other_emails}.values()
            for email in unique_emails:
                save_validated(UserEmail(user=user, email=email))


@router.get("", response=list[UserOut])
@paginate
def list_users(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    filters: Query[UserFilters],
) -> QuerySet[User]:
    """Lists users by name.

    `q` searches names and every email. `email` matches a primary or other email
    exactly, ignoring case.

    Returns:
        The matching users.
    """
    users = _users()
    if filters.q:
        users = users.filter(
            Q(name__icontains=filters.q)
            | Q(preferred_name__icontains=filters.q)
            | Q(email__icontains=filters.q)
            | Q(other_emails__email__icontains=filters.q)
        )
    if filters.email:
        users = users.filter(
            Q(email__iexact=filters.email)
            | Q(other_emails__email__iexact=filters.email)
        )
    if filters.orcid:
        users = users.filter(orcid=filters.orcid)
    if filters.gpm_uuid:
        users = users.filter(gpm_uuid=filters.gpm_uuid)
    return users.distinct()


@router.get("/gpm-uuid/{gpm_uuid}", response=UserDetail)
def get_user_by_gpm_uuid(request: HttpRequest, gpm_uuid: uuid.UUID) -> User:  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    """Gets the user with this GPM UUID.

    Returns:
        The user.
    """
    return get_object_or_404(_users(), gpm_uuid=gpm_uuid)


@router.get("/{id}", response=UserDetail)
def get_user(request: HttpRequest, id_: PathEx[uuid.UUID, P(alias="id")]) -> User:  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    """Gets one user.

    Returns:
        The user.
    """
    return get_object_or_404(_users(), pk=id_)


@router.post("", response={201: UserDetail})
def create_user(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    data: UserIn,
) -> Status[User]:
    """Creates a user. No two users share an email, ignoring case.

    Returns:
        201 and the new user.
    """
    changes = data.dict()
    other_emails = changes.pop("other_emails")
    user = User()
    _save(user, changes, other_emails)
    return Status(201, get_object_or_404(_users(), pk=user.pk))


@router.patch("/{id}", response=UserDetail)
def update_user(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    id_: PathEx[uuid.UUID, P(alias="id")],
    data: UserPatch,
) -> User:
    """Changes a user. Sending other_emails replaces the list.

    Returns:
        The changed user.
    """
    return _update_user(get_object_or_404(User, pk=id_), data)


def _update_user(user: User, data: UserPatch) -> User:
    """Applies a PATCH to a user.

    Returns:
        The changed user.
    """
    changes = data.dict(exclude_unset=True)
    other_emails = changes.pop("other_emails", None)
    _save(user, changes, other_emails)
    return get_object_or_404(_users(), pk=user.pk)


@router.delete("/{id}", response={204: None})
def delete_user(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    id_: PathEx[uuid.UUID, P(alias="id")],
) -> Status[None]:
    """Deletes a user, with their memberships and other emails.

    Its history keeps what it held.

    Returns:
        204.
    """
    get_object_or_404(User, pk=id_).delete()
    return Status(204, None)


@router.patch("/gpm-uuid/{gpm_uuid}", response=UserDetail)
def update_user_by_gpm_uuid(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    gpm_uuid: uuid.UUID,
    data: UserPatch,
) -> User:
    """Changes the user with this GPM UUID, as `PATCH /users/{{id}}` does.

    Returns:
        The changed user.
    """
    return _update_user(get_object_or_404(User, gpm_uuid=gpm_uuid), data)


@router.delete("/gpm-uuid/{gpm_uuid}", response={204: None})
def delete_user_by_gpm_uuid(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    gpm_uuid: uuid.UUID,
) -> Status[None]:
    """Deletes the user with this GPM UUID, with their memberships and other emails.

    Its history keeps what it held.

    Returns:
        204.
    """
    get_object_or_404(User, gpm_uuid=gpm_uuid).delete()
    return Status(204, None)
