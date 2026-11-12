"""Serves the AS API's membership endpoints."""

import uuid
from datetime import date, datetime

from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import P, Query, Router, Schema, Status
from ninja.pagination import paginate
from ninja.params import PathEx
from pydantic import ConfigDict

from affiliations_service.api.helpers import save_validated
from affiliations_service.models import Affiliation, Membership, User

router = Router()


class MembershipOut(Schema):
    """A role a user holds in an affiliation."""

    id: uuid.UUID
    user: uuid.UUID
    affiliation: uuid.UUID
    role: Membership.Role
    start_date: date | None
    end_date: date | None
    is_current: bool
    added_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_user(membership: Membership) -> uuid.UUID:
        """Returns the user's ID."""
        return membership.user_id  # ty: ignore[unresolved-attribute] (Django adds user_id.)

    @staticmethod
    def resolve_affiliation(membership: Membership) -> uuid.UUID:
        """Returns the affiliation's ID."""
        return membership.affiliation_id  # ty: ignore[unresolved-attribute] (Django adds affiliation_id.)


class MembershipIn(Schema):
    """The fields for a new membership."""

    model_config = ConfigDict(extra="forbid")

    user: uuid.UUID
    affiliation: uuid.UUID
    role: Membership.Role
    start_date: date | None = None
    end_date: date | None = None


class MembershipPatch(Schema):
    """The dates to change on a membership. Set end_date to end it."""

    model_config = ConfigDict(extra="forbid")

    start_date: date | None = None
    end_date: date | None = None


class MembershipFilters(Schema):
    """Narrows the list of memberships."""

    affiliation: uuid.UUID | None = None
    user: uuid.UUID | None = None
    role: Membership.Role | None = None
    current: bool | None = None


def _get_or_400[T: (User, Affiliation)](model: type[T], pk: uuid.UUID) -> T:
    """Returns the user or affiliation with this ID.

    Raises:
        ValidationError: If there's none, so the API returns a 400.
    """
    try:
        return model.objects.get(pk=pk)
    except model.DoesNotExist:
        error_message = f"There's no {model._meta.verbose_name} with that ID."  # ruff: ignore[private-member-access]
        raise ValidationError(error_message) from None


@router.get("", response=list[MembershipOut])
@paginate
def list_memberships(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    filters: Query[MembershipFilters],
) -> QuerySet[Membership]:
    """Lists memberships. `current=true` leaves out ended ones; `false` keeps only them.

    Returns:
        The matching memberships.
    """
    memberships = Membership.objects.all()
    if filters.current is not None:
        current = Membership.objects.current()
        memberships = (
            memberships.filter(pk__in=current)
            if filters.current
            else memberships.exclude(pk__in=current)
        )
    exact = {
        "affiliation_id": filters.affiliation,
        "user_id": filters.user,
        "role": filters.role,
    }
    return memberships.filter(
        **{field: value for field, value in exact.items() if value is not None}
    )


@router.get("/{id}", response=MembershipOut)
def get_membership(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    id_: PathEx[uuid.UUID, P(alias="id")],
) -> Membership:
    """Gets one membership.

    Returns:
        The membership.
    """
    return get_object_or_404(Membership, pk=id_)


@router.post("", response={201: MembershipOut})
def create_membership(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    data: MembershipIn,
) -> Status[Membership]:
    """Gives a user a role in an affiliation.

    Returns:
        201 and the new membership.

    Raises:
        ValidationError: If the affiliation is deleted, so the API returns a 400.
    """
    affiliation = _get_or_400(Affiliation, data.affiliation)
    if affiliation.is_deleted:
        error_message = "That affiliation has been deleted."
        raise ValidationError(error_message)
    membership = Membership(
        user=_get_or_400(User, data.user),
        affiliation=affiliation,
        role=data.role,
        start_date=data.start_date,
        end_date=data.end_date,
    )
    save_validated(membership)
    return Status(201, membership)


@router.patch("/{id}", response=MembershipOut)
def update_membership(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    id_: PathEx[uuid.UUID, P(alias="id")],
    data: MembershipPatch,
) -> Membership:
    """Changes a membership's dates. Setting end_date ends it; it isn't deleted.

    Returns:
        The changed membership.
    """
    membership = get_object_or_404(Membership, pk=id_)
    save_validated(membership, data.dict(exclude_unset=True))
    return membership
