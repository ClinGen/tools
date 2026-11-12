"""Serves the AS API's CDWG endpoints."""

import uuid

from django.db.models import QuerySet
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
    is_deleted: bool


class CDWGIn(Schema):
    """The fields for a new CDWG."""

    name: str
    gpm_uuid: uuid.UUID | None = None


class CDWGPatch(Schema):
    """The fields to change on a CDWG. Leave out the ones that don't change."""

    name: str | None = None
    gpm_uuid: uuid.UUID | None = None


@router.get("", response=list[CDWGOut])
@paginate
def list_cdwgs(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    include_deleted: bool = False,  # ruff: ignore[boolean-type-hint-positional-argument, boolean-default-value-positional-argument] (A query parameter.)
) -> QuerySet[CDWG]:
    """Lists the CDWGs by name, leaving out deleted ones unless include_deleted is true.

    Returns:
        The CDWGs.
    """
    return CDWG.objects.all() if include_deleted else CDWG.objects.active()


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
    """Marks a CDWG deleted.

    It's kept, but left out of lists.

    Returns:
        204.
    """
    get_object_or_404(CDWG, pk=id_).delete()
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
    """Marks the CDWG with this GPM UUID deleted.

    It's kept, but left out of lists.

    Returns:
        204.
    """
    get_object_or_404(CDWG, gpm_uuid=gpm_uuid).delete()
    return Status(204, None)
