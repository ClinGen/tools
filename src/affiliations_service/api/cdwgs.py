"""Serves the AS API's CDWG endpoints."""

import uuid

from django.core.exceptions import ValidationError
from django.db.models import ProtectedError, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import P, Router, Schema, Status
from ninja.pagination import paginate
from ninja.params import PathEx

from affiliations_service.api.helpers import save_validated
from affiliations_service.models import CDWG

router = Router()


class CDWGOut(Schema):
    """A Clinical Domain Working Group."""

    id: uuid.UUID
    name: str
    gpm_uuid: uuid.UUID | None


class CDWGIn(Schema):
    """The fields for a new CDWG."""

    name: str
    gpm_uuid: uuid.UUID | None = None


class CDWGPatch(Schema):
    """The fields to change on a CDWG. Leave out the ones that don't change."""

    name: str | None = None
    gpm_uuid: uuid.UUID | None = None


def _delete(cdwg: CDWG) -> None:
    """Deletes a CDWG that no affiliation belongs to.

    Raises:
        ValidationError: If an affiliation, even a deleted one, belongs to the CDWG,
            so the API returns a 400.
    """
    try:
        cdwg.delete()
    except ProtectedError:
        error_message = "This CDWG still has affiliations, so it can't be deleted."
        raise ValidationError(error_message) from None


@router.get("", response=list[CDWGOut])
@paginate
def list_cdwgs(request: HttpRequest) -> QuerySet[CDWG]:  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    """Lists the CDWGs by name.

    Returns:
        The CDWGs.
    """
    return CDWG.objects.all()


@router.get("/gpm-uuid/{gpm_uuid}", response=CDWGOut)
def get_cdwg_by_gpm_uuid(request: HttpRequest, gpm_uuid: uuid.UUID) -> CDWG:  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    """Gets the CDWG with this GPM UUID.

    Returns:
        The CDWG.
    """
    return get_object_or_404(CDWG, gpm_uuid=gpm_uuid)


@router.get("/{id}", response=CDWGOut)
def get_cdwg(request: HttpRequest, id_: PathEx[uuid.UUID, P(alias="id")]) -> CDWG:  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    """Gets one CDWG.

    Returns:
        The CDWG.
    """
    return get_object_or_404(CDWG, pk=id_)


@router.post("", response={201: CDWGOut})
def create_cdwg(request: HttpRequest, data: CDWGIn) -> Status[CDWG]:  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    """Creates a CDWG. Its name must differ from every other CDWG's, ignoring case.

    Returns:
        201 and the new CDWG.
    """
    cdwg = CDWG()
    save_validated(cdwg, data.dict())
    return Status(201, cdwg)


@router.patch("/{id}", response=CDWGOut)
def update_cdwg(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    id_: PathEx[uuid.UUID, P(alias="id")],
    data: CDWGPatch,
) -> CDWG:
    """Changes a CDWG's name or GPM UUID.

    Returns:
        The changed CDWG.
    """
    return _update_cdwg(get_object_or_404(CDWG, pk=id_), data)


def _update_cdwg(cdwg: CDWG, data: CDWGPatch) -> CDWG:
    """Applies a PATCH to a CDWG.

    Returns:
        The changed CDWG.
    """
    save_validated(cdwg, data.dict(exclude_unset=True))
    return cdwg


@router.delete("/{id}", response={204: None})
def delete_cdwg(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    id_: PathEx[uuid.UUID, P(alias="id")],
) -> Status[None]:
    """Deletes a CDWG.

    Its history keeps what it held.

    Returns:
        204.
    """
    _delete(get_object_or_404(CDWG, pk=id_))
    return Status(204, None)


@router.patch("/gpm-uuid/{gpm_uuid}", response=CDWGOut)
def update_cdwg_by_gpm_uuid(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    gpm_uuid: uuid.UUID,
    data: CDWGPatch,
) -> CDWG:
    """Changes the CDWG with this GPM UUID, as `PATCH /cdwgs/{{id}}` does.

    Returns:
        The changed CDWG.
    """
    return _update_cdwg(get_object_or_404(CDWG, gpm_uuid=gpm_uuid), data)


@router.delete("/gpm-uuid/{gpm_uuid}", response={204: None})
def delete_cdwg_by_gpm_uuid(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    gpm_uuid: uuid.UUID,
) -> Status[None]:
    """Deletes the CDWG with this GPM UUID.

    Its history keeps what it held.

    Returns:
        204.
    """
    _delete(get_object_or_404(CDWG, gpm_uuid=gpm_uuid))
    return Status(204, None)
