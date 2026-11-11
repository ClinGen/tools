"""Serves the AS API's CDWG endpoints."""

import uuid

from django.db.models import QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema, Status
from ninja.pagination import paginate

from affiliations_service.api.helpers import save_validated
from affiliations_service.models import CDWG

router = Router()


class CdwgOut(Schema):
    """A Clinical Domain Working Group."""

    id: uuid.UUID
    name: str
    gpm_uuid: uuid.UUID | None


class CdwgIn(Schema):
    """The fields for a new CDWG."""

    name: str
    gpm_uuid: uuid.UUID | None = None


class CdwgPatch(Schema):
    """The fields to change on a CDWG. Leave out the ones that don't change."""

    name: str | None = None
    gpm_uuid: uuid.UUID | None = None


@router.get("", response=list[CdwgOut])
@paginate
def list_cdwgs(request: HttpRequest) -> QuerySet[CDWG]:  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    """Lists the CDWGs by name.

    Returns:
        The CDWGs.
    """
    return CDWG.objects.all()


@router.get("/{cdwg_id}", response=CdwgOut)
def get_cdwg(request: HttpRequest, cdwg_id: uuid.UUID) -> CDWG:  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    """Gets one CDWG.

    Returns:
        The CDWG.
    """
    return get_object_or_404(CDWG, pk=cdwg_id)


@router.post("", response={201: CdwgOut})
def create_cdwg(request: HttpRequest, data: CdwgIn) -> Status[CDWG]:  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    """Creates a CDWG. Its name must differ from every other CDWG's, ignoring case.

    Returns:
        201 and the new CDWG.
    """
    cdwg = CDWG()
    save_validated(cdwg, data.dict())
    return Status(201, cdwg)


@router.patch("/{cdwg_id}", response=CdwgOut)
def update_cdwg(request: HttpRequest, cdwg_id: uuid.UUID, data: CdwgPatch) -> CDWG:  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    """Changes a CDWG's name or GPM UUID.

    Returns:
        The changed CDWG.
    """
    cdwg = get_object_or_404(CDWG, pk=cdwg_id)
    save_validated(cdwg, data.dict(exclude_unset=True))
    return cdwg
