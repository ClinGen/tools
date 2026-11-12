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
    cdwg = get_object_or_404(CDWG, pk=id_)
    save_validated(cdwg, data.dict(exclude_unset=True))
    return cdwg
