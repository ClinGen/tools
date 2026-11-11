"""Serves the AS API's affiliation endpoints."""

import uuid
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Schema, Status
from ninja.pagination import paginate
from pydantic import ConfigDict

from affiliations_service.api.cdwgs import CdwgOut
from affiliations_service.api.helpers import save_validated
from affiliations_service.models import CDWG, Affiliation, ClinVarSubmitterId

router = Router()

# Other systems use these to refer to an affiliation, so they can't change.
LOCKED_FIELDS = ["affiliation_id", "expert_panel_id", "type", "gpm_uuid"]


class AffiliationOut(Schema):
    """An affiliation, with its CDWG and ClinVar submitter IDs."""

    id: uuid.UUID
    affiliation_id: int
    expert_panel_id: int | None
    type: Affiliation.Type
    status: Affiliation.Status
    full_name: str
    short_name: str
    cdwg: CdwgOut
    gpm_uuid: uuid.UUID | None
    clinvar_submitter_ids: list[str]
    is_deleted: bool
    added_at: datetime
    updated_at: datetime

    @staticmethod
    def resolve_clinvar_submitter_ids(affiliation: Affiliation) -> list[str]:
        """Returns the affiliation's ClinVar submitter IDs as strings."""
        return [item.submitter_id for item in affiliation.clinvar_submitter_ids.all()]  # ty: ignore[unresolved-attribute] (Django adds the reverse relation.)


class AffiliationIn(Schema):
    """The fields for a new affiliation. The AS assigns its IDs."""

    model_config = ConfigDict(extra="forbid")

    type: Affiliation.Type
    full_name: str
    short_name: str = ""
    status: Affiliation.Status = Affiliation.Status.APPLYING
    cdwg: uuid.UUID
    gpm_uuid: uuid.UUID | None = None
    clinvar_submitter_ids: list[str] = []


class AffiliationPatch(Schema):
    """The fields to change on an affiliation. Leave out the ones that don't change.

    The IDs, type, and GPM UUID can't change; sending a different value is a 400.
    """

    model_config = ConfigDict(extra="forbid")

    full_name: str | None = None
    short_name: str | None = None
    status: Affiliation.Status | None = None
    cdwg: uuid.UUID | None = None
    clinvar_submitter_ids: list[str] | None = None
    affiliation_id: int | None = None
    expert_panel_id: int | None = None
    type: Affiliation.Type | None = None
    gpm_uuid: uuid.UUID | None = None


class AffiliationFilters(Schema):
    """Narrows the list of affiliations."""

    type: Affiliation.Type | None = None
    status: Affiliation.Status | None = None
    cdwg: uuid.UUID | None = None
    affiliation_id: int | None = None
    expert_panel_id: int | None = None
    q: str | None = None
    include_deleted: bool = False


def _get_cdwg(cdwg_id: uuid.UUID) -> CDWG:
    """Returns the CDWG with this ID.

    Raises:
        ValidationError: If there's no such CDWG, so the API returns a 400.
    """
    try:
        return CDWG.objects.get(pk=cdwg_id)
    except CDWG.DoesNotExist:
        error_message = "There's no CDWG with that ID."
        raise ValidationError(error_message) from None


def _save(
    affiliation: Affiliation, changes: dict, submitter_ids: list[str] | None
) -> None:
    """Saves an affiliation and, if given, replaces its ClinVar submitter IDs."""
    if "cdwg" in changes:
        changes["cdwg"] = _get_cdwg(changes["cdwg"])
    with transaction.atomic():
        save_validated(affiliation, changes)
        if submitter_ids is not None:
            affiliation.clinvar_submitter_ids.all().delete()  # ty: ignore[unresolved-attribute] (Django adds the reverse relation.)
            ClinVarSubmitterId.objects.bulk_create(
                ClinVarSubmitterId(affiliation=affiliation, submitter_id=submitter_id)
                for submitter_id in dict.fromkeys(submitter_ids)
            )


def _affiliations() -> QuerySet[Affiliation]:
    return Affiliation.objects.select_related("cdwg").prefetch_related(
        "clinvar_submitter_ids"
    )


@router.get("", response=list[AffiliationOut])
@paginate
def list_affiliations(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    filters: Query[AffiliationFilters],
) -> QuerySet[Affiliation]:
    """Lists affiliations by affiliation ID, leaving out deleted ones by default.

    `q` searches the full and short names.

    Returns:
        The matching affiliations.
    """
    affiliations = _affiliations()
    if not filters.include_deleted:
        affiliations = affiliations.filter(is_deleted=False)
    exact = {
        "type": filters.type,
        "status": filters.status,
        "cdwg_id": filters.cdwg,
        "affiliation_id": filters.affiliation_id,
        "expert_panel_id": filters.expert_panel_id,
    }
    affiliations = affiliations.filter(
        **{field: value for field, value in exact.items() if value is not None}
    )
    if filters.q:
        affiliations = affiliations.filter(
            Q(full_name__icontains=filters.q) | Q(short_name__icontains=filters.q)
        )
    return affiliations


@router.get("/{affiliation_id}", response=AffiliationOut)
def get_affiliation(request: HttpRequest, affiliation_id: uuid.UUID) -> Affiliation:  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    """Gets one affiliation, even if it's deleted.

    Returns:
        The affiliation.
    """
    return get_object_or_404(_affiliations(), pk=affiliation_id)


@router.post("", response={201: AffiliationOut})
def create_affiliation(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    data: AffiliationIn,
) -> Status[Affiliation]:
    """Creates an affiliation and assigns its affiliation and expert panel IDs.

    Returns:
        201 and the new affiliation.
    """
    changes = data.dict()
    submitter_ids = changes.pop("clinvar_submitter_ids")
    affiliation = Affiliation()
    _save(affiliation, changes, submitter_ids)
    return Status(201, get_object_or_404(_affiliations(), pk=affiliation.pk))


@router.patch("/{affiliation_id}", response=AffiliationOut)
def update_affiliation(
    request: HttpRequest,  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    affiliation_id: uuid.UUID,
    data: AffiliationPatch,
) -> Affiliation:
    """Changes an affiliation. Sending clinvar_submitter_ids replaces the list.

    Returns:
        The changed affiliation.

    Raises:
        ValidationError: If the request changes a locked field, so the API returns a
            400.
    """
    affiliation = get_object_or_404(Affiliation, pk=affiliation_id)
    changes = data.dict(exclude_unset=True)
    for field in LOCKED_FIELDS:
        if field in changes and changes.pop(field) != getattr(affiliation, field):
            error_message = f"An affiliation's {field} can't be changed."
            raise ValidationError(error_message)
    submitter_ids = changes.pop("clinvar_submitter_ids", None)
    _save(affiliation, changes, submitter_ids)
    return get_object_or_404(_affiliations(), pk=affiliation.pk)


@router.delete("/{affiliation_id}", response={204: None})
def delete_affiliation(request: HttpRequest, affiliation_id: uuid.UUID) -> Status[None]:  # ruff: ignore[unused-function-argument] (Ninja's signature.)
    """Marks an affiliation deleted. It's kept, but left out of lists.

    Returns:
        204.
    """
    get_object_or_404(Affiliation, pk=affiliation_id).delete()
    return Status(204, None)
