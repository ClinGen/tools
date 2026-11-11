"""Describes the records the CSS accepts and the content it sends to ClinVar.

A client sends a `RecordRequest`: its affiliation and one germline record. A record is
validated against `GermlineRecord`, and a batch's content against `Content`, which is
the part of ClinVar's submission schema the CSS models: germline variant
classifications, one condition and one observation each. Field names are ClinVar's, as
aliases, and a field the CSS doesn't model is rejected, so a record's fields always
hold everything that's forwarded. Functions copy them into model fields.
"""

from datetime import date
from typing import Any, Self

from ninja import Field, Schema
from pydantic import ConfigDict, model_validator

from clinvar_submission_service.models import (
    AffectedStatus,
    AlleleOrigin,
    Assembly,
    AssertionCriteriaDb,
    Classification,
    CollectionMethod,
    ConditionDb,
    ModeOfInheritance,
    RecordStatus,
    ReleaseStatus,
)

# The most records ClinVar accepts in one submission.
MAX_RECORDS = 10_000


class ClinVarSchema(Schema):
    """Rejects any field the CSS doesn't model."""

    model_config = ConfigDict(extra="forbid")


class AssertionCriteria(ClinVarSchema):
    db: AssertionCriteriaDb
    id: str


class Gene(ClinVarSchema):
    symbol: str


class Variant(ClinVarSchema):
    hgvs: str
    gene: list[Gene] | None = Field(None, min_length=1, max_length=1)


class VariantSet(ClinVarSchema):
    variant: list[Variant] = Field(min_length=1, max_length=1)


class Condition(ClinVarSchema):
    db: ConditionDb
    id: str


class ConditionSet(ClinVarSchema):
    condition: list[Condition] = Field(min_length=1, max_length=1)


class GermlineClassification(ClinVarSchema):
    description: Classification = Field(alias="germlineClassificationDescription")
    mode_of_inheritance: ModeOfInheritance | None = Field(
        None, alias="modeOfInheritance"
    )
    date_last_evaluated: date | None = Field(None, alias="dateLastEvaluated")
    comment: str | None = None


class ObservedIn(ClinVarSchema):
    allele_origin: AlleleOrigin = Field(alias="alleleOrigin")
    affected_status: AffectedStatus = Field(alias="affectedStatus")
    collection_method: CollectionMethod = Field(alias="collectionMethod")


class GermlineRecord(ClinVarSchema):
    record_status: RecordStatus = Field(alias="recordStatus")
    clinvar_accession: str | None = Field(None, alias="clinvarAccession")
    local_id: str | None = Field(None, alias="localID")
    local_key: str | None = Field(None, alias="localKey")
    submitted_assembly: Assembly = Field(alias="submittedAssembly")
    variant_set: VariantSet = Field(alias="variantSet")
    condition_set: ConditionSet = Field(alias="conditionSet")
    germline_classification: GermlineClassification = Field(
        alias="germlineClassification"
    )
    observed_in: list[ObservedIn] = Field(
        alias="observedIn", min_length=1, max_length=1
    )

    @model_validator(mode="after")
    def check_update_has_accession(self) -> Self:
        """Requires an update's SCV, which says which ClinVar record it changes.

        Returns:
            The record.

        Raises:
            ValueError: If the record is an update without a ClinVar accession.
        """
        if self.record_status == RecordStatus.UPDATE and not self.clinvar_accession:
            error_message = "An update needs the clinvarAccession of the record."
            raise ValueError(error_message)
        return self


class Content(ClinVarSchema):
    """A submission's ClinVar content: up to 10,000 germline records."""

    germline_batch: list[GermlineRecord] = Field(
        alias="germlineSubmission", min_length=1, max_length=MAX_RECORDS
    )
    assertion_criteria: AssertionCriteria | None = Field(
        None, alias="assertionCriteria"
    )
    behalf_org_id: int | None = Field(None, alias="behalfOrgID", ge=1)
    release_status: ReleaseStatus | None = Field(
        None, alias="clinvarSubmissionReleaseStatus"
    )


class Affiliation(ClinVarSchema):
    """The curation group whose classifications a submission holds."""

    id: int = Field(ge=1, description="The affiliation's ID in the AS, such as 10007.")
    name: str = Field(min_length=1, description="The affiliation's name.")


class RecordRequest(ClinVarSchema):
    """The body a client sends: its affiliation and one germline record."""

    affiliation: Affiliation
    record: GermlineRecord


def batch_fields(content: Content) -> dict[str, Any]:
    """Returns the content's fields for its Batch.

    Returns:
        The Batch field values, by field name.
    """
    criteria = content.assertion_criteria
    return {
        "assertion_criteria_db": criteria.db if criteria else "",
        "assertion_criteria_id": criteria.id if criteria else "",
        "behalf_org_id": content.behalf_org_id,
        "release_status": content.release_status or "",
    }


def record_fields(content: Content) -> list[dict[str, Any]]:
    """Returns the fields of a Record for each of the content's records.

    Returns:
        One dictionary of Record field values, by field name, per record, in the
        content's order.
    """
    return [fields_of(record) for record in content.germline_batch]


def fields_of(record: GermlineRecord) -> dict[str, Any]:
    """Returns the fields of a Record for one germline record.

    Returns:
        The Record field values, by field name.
    """
    variant = record.variant_set.variant[0]
    condition = record.condition_set.condition[0]
    classification = record.germline_classification
    observation = record.observed_in[0]
    return {
        "record_status": record.record_status,
        "clinvar_accession": record.clinvar_accession or "",
        "local_id": record.local_id or "",
        "local_key": record.local_key or "",
        "submitted_assembly": record.submitted_assembly,
        "hgvs": variant.hgvs,
        "gene_symbol": variant.gene[0].symbol if variant.gene else "",
        "condition_db": condition.db,
        "condition_id": condition.id,
        "classification": classification.description,
        "mode_of_inheritance": classification.mode_of_inheritance or "",
        "date_last_evaluated": classification.date_last_evaluated,
        "comment": classification.comment or "",
        "allele_origin": observation.allele_origin,
        "affected_status": observation.affected_status,
        "collection_method": observation.collection_method,
    }
