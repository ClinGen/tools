"""Houses database models for the clinvar_submission_service app."""

import hashlib
import secrets
from typing import ClassVar

from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone
from simple_history.models import HistoricalRecords

from common.models import SlugModel, UUIDModel

# ClinVar's terms, from its submission schema. Each choice's value is exactly what
# ClinVar expects in the batch's content.


class AssertionCriteriaDb(models.TextChoices):
    PUBMED = "PubMed", "PubMed"
    DOI = "DOI", "DOI"
    PMC = "pmc", "PubMed Central"


class ReleaseStatus(models.TextChoices):
    PUBLIC = "public", "Public"
    HOLD_UNTIL_PUBLISHED = "hold until published", "Hold Until Published"


class RecordStatus(models.TextChoices):
    NOVEL = "novel", "Novel"
    UPDATE = "update", "Update"


class Assembly(models.TextChoices):
    GRCH38 = "GRCh38", "GRCh38"
    HG38 = "hg38", "hg38"
    GRCH37 = "GRCh37", "GRCh37"
    HG19 = "hg19", "hg19"
    NCBI36 = "NCBI36", "NCBI36"
    HG18 = "hg18", "hg18"
    NOT_APPLICABLE = "not applicable", "Not Applicable"


class ConditionDb(models.TextChoices):
    OMIM = "OMIM", "OMIM"
    MEDGEN = "MedGen", "MedGen"
    ORPHANET = "Orphanet", "Orphanet"
    MESH = "MeSH", "MeSH"
    HP = "HP", "HPO"
    MONDO = "MONDO", "Mondo"


class Classification(models.TextChoices):
    """The five ACMG classifications, the only ones the VCI makes."""

    PATHOGENIC = "Pathogenic", "Pathogenic"
    LIKELY_PATHOGENIC = "Likely pathogenic", "Likely Pathogenic"
    UNCERTAIN_SIGNIFICANCE = "Uncertain significance", "Uncertain Significance"
    LIKELY_BENIGN = "Likely benign", "Likely Benign"
    BENIGN = "Benign", "Benign"


class ModeOfInheritance(models.TextChoices):
    AUTOSOMAL_DOMINANT = "Autosomal dominant inheritance"
    AUTOSOMAL_RECESSIVE = "Autosomal recessive inheritance"
    MITOCHONDRIAL = "Mitochondrial inheritance"
    GENETIC_ANTICIPATION = "Genetic anticipation"
    SPORADIC = "Sporadic"
    SEX_LIMITED_AUTOSOMAL_DOMINANT = "Sex-limited autosomal dominant"
    X_LINKED_RECESSIVE = "X-linked recessive inheritance"
    X_LINKED_DOMINANT = "X-linked dominant inheritance"
    Y_LINKED = "Y-linked inheritance"
    OTHER = "Other"
    X_LINKED = "X-linked inheritance"
    CODOMINANT = "Codominant"
    SEMIDOMINANT = "Semidominant inheritance"
    AUTOSOMAL_UNKNOWN = "Autosomal unknown"
    AUTOSOMAL_DOMINANT_MATERNAL_IMPRINTING = (
        "Autosomal dominant inheritance with maternal imprinting"
    )
    AUTOSOMAL_DOMINANT_PATERNAL_IMPRINTING = (
        "Autosomal dominant inheritance with paternal imprinting"
    )
    MULTIFACTORIAL = "Multifactorial inheritance"
    UNKNOWN_MECHANISM = "Unknown mechanism"
    OLIGOGENIC = "Oligogenic inheritance"


class AlleleOrigin(models.TextChoices):
    GERMLINE = "germline", "Germline"
    SOMATIC = "somatic", "Somatic"
    DE_NOVO = "de novo", "De Novo"
    UNKNOWN = "unknown", "Unknown"
    INHERITED = "inherited", "Inherited"
    MATERNAL = "maternal", "Maternal"
    PATERNAL = "paternal", "Paternal"
    BIPARENTAL = "biparental", "Biparental"
    NOT_APPLICABLE = "not applicable", "Not Applicable"


class AffectedStatus(models.TextChoices):
    YES = "yes", "Yes"
    NO = "no", "No"
    UNKNOWN = "unknown", "Unknown"
    NOT_PROVIDED = "not provided", "Not Provided"
    NOT_APPLICABLE = "not applicable", "Not Applicable"


class CollectionMethod(models.TextChoices):
    CURATION = "curation", "Curation"
    LITERATURE_ONLY = "literature only", "Literature Only"
    REFERENCE_POPULATION = "reference population", "Reference Population"
    PROVIDER_INTERPRETATION = "provider interpretation", "Provider Interpretation"
    PHENOTYPING_ONLY = "phenotyping only", "Phenotyping Only"
    CASE_CONTROL = "case-control", "Case-Control"
    CLINICAL_TESTING = "clinical testing", "Clinical Testing"
    IN_VITRO = "in vitro", "In Vitro"
    IN_VIVO = "in vivo", "In Vivo"
    RESEARCH = "research", "Research"
    NOT_PROVIDED = "not provided", "Not Provided"


class BatchManager(models.Manager["Batch"]):
    def due_to_poll(self) -> models.QuerySet["Batch"]:
        """Returns the pollable batches whose next poll time has passed.

        The ones that have waited longest come first.
        """
        return self.filter(
            status__in=Batch.POLLABLE_STATUSES,
            next_poll_at__lte=timezone.now(),
        ).order_by("next_poll_at")


class Batch(SlugModel):
    """One request to ClinVar, from receipt to a final ClinVar status.

    It's saved before it's forwarded to ClinVar, so there's a record of every request,
    even one ClinVar never got. Its slug is B and the start of its UUID, such as
    B3f2a9c1e.
    """

    slug_prefix = "B"

    class Status(models.TextChoices):
        """Where the batch is, relative to ClinVar.

        The first two are the CSS's own: ClinVar doesn't have the batch. The rest
        are ClinVar's statuses from its Submission API (submitted, processing,
        processed, and error), which the poller reads.
        """

        NOT_SENT_TO_CLINVAR = "not_sent_to_clinvar", "Not Sent"
        SEND_TO_CLINVAR_FAILED = "send_to_clinvar_failed", "Send Failed"
        SUBMITTED_TO_CLINVAR = "submitted_to_clinvar", "Submitted"
        PROCESSING_AT_CLINVAR = "processing_at_clinvar", "Processing"
        PROCESSED_BY_CLINVAR = "processed_by_clinvar", "Processed"
        ERROR_AT_CLINVAR = "error_at_clinvar", "Error"

    # What each status means, for its tooltip. ClinVar's four follow the descriptions in
    # its Submission API docs, which call a submission a batch.
    STATUS_HELP: ClassVar[dict[str, str]] = {
        Status.NOT_SENT_TO_CLINVAR: (
            "The CSS has this batch but hasn't sent it to ClinVar yet."
        ),
        Status.SEND_TO_CLINVAR_FAILED: (
            "The CSS tried to send this batch to ClinVar, but ClinVar didn't get "
            "it. You can resend it from its page."
        ),
        Status.SUBMITTED_TO_CLINVAR: (
            "ClinVar has received the batch, and it's waiting to be validated."
        ),
        Status.PROCESSING_AT_CLINVAR: (
            "ClinVar is validating the batch, which should be done soon."
        ),
        Status.PROCESSED_BY_CLINVAR: "All records in the batch succeeded.",
        Status.ERROR_AT_CLINVAR: "One or more records in the batch failed.",
    }

    # What an error status means, by ClinVar's error code.
    ERROR_CODE_HELP: ClassVar[dict[int, str]] = {
        1: "Some records in the batch succeeded, and others failed.",
        2: "All records in the batch failed.",
    }

    # The statuses the poller checks on. A batch not sent to ClinVar, or whose send
    # failed, has no ClinVar ID to poll; the rest are final.
    POLLABLE_STATUSES: ClassVar[list[str]] = [
        Status.SUBMITTED_TO_CLINVAR,
        Status.PROCESSING_AT_CLINVAR,
    ]

    api_key = models.ForeignKey(
        "ApiKey",
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="batches",
        verbose_name="Client",
        help_text="The API key of the client that sent the batch.",
    )
    affiliation_id = models.PositiveIntegerField(
        blank=True,
        db_index=True,
        null=True,
        verbose_name="Affiliation ID",
        help_text="The AS ID of the curation group whose classifications these are.",
    )
    affiliation_name = models.CharField(
        blank=True,
        default="",
        max_length=255,
        verbose_name="Affiliation",
        help_text="The curation group's name, as the client sent it.",
    )
    records = models.ManyToManyField(
        "Record",
        through="BatchRecord",
        related_name="batches",
        verbose_name="Records",
        help_text="The records in the batch.",
    )
    assertion_criteria_db = models.CharField(
        blank=True,
        choices=AssertionCriteriaDb.choices,
        default="",
        max_length=8,
        verbose_name="Assertion Criteria Database",
        help_text="Where the criteria used to classify the variants are published.",
    )
    assertion_criteria_id = models.CharField(
        blank=True,
        default="",
        max_length=255,
        verbose_name="Assertion Criteria ID",
        help_text="The criteria's ID in that database, such as a PubMed ID.",
    )
    behalf_org_id = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name="On Behalf Of",
        help_text="The ClinVar ID of the organization the batch is made for.",
    )
    release_status = models.CharField(
        blank=True,
        choices=ReleaseStatus.choices,
        default="",
        max_length=32,
        verbose_name="Release Status",
        help_text="Whether ClinVar may make the records public. Blank means public.",
    )
    clinvar_submission_id = models.CharField(
        blank=True,
        default="",
        max_length=32,  # A ClinVar submission ID is of the form SUB1234567.
        verbose_name="ClinVar Submission ID",
        help_text=(
            "The ID ClinVar returned, e.g., SUB999999. Blank until ClinVar accepts "
            "the batch."
        ),
    )
    status = models.CharField(
        choices=Status.choices,
        default=Status.NOT_SENT_TO_CLINVAR,
        max_length=32,
        verbose_name="Status",
        help_text="Where the batch is between receipt and a final ClinVar status.",
    )
    clinvar_updated_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="ClinVar Updated At",
        help_text="When ClinVar last updated the batch's status.",
    )
    clinvar_error_code = models.PositiveSmallIntegerField(
        blank=True,
        null=True,
        verbose_name="ClinVar Error Code",
        help_text=(
            "ClinVar's error code: 1 means some records failed, and 2 means every "
            "record failed."
        ),
    )
    latest_response = models.JSONField(
        blank=True,
        null=True,
        verbose_name="Latest Response",
        help_text="ClinVar's most recent response for the batch.",
    )
    summary_report = models.JSONField(
        blank=True,
        null=True,
        verbose_name="Summary Report",
        help_text="ClinVar's summary report. Empty until processing finishes.",
    )
    error_message = models.TextField(
        blank=True,
        default="",
        verbose_name="Error Message",
        help_text="What went wrong, if anything.",
    )
    added_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Added At",
        help_text="When the batch was received.",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
        help_text="When the batch was last updated.",
    )
    last_polled_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Last Polled At",
        help_text="When the poller last checked ClinVar for this batch.",
    )
    next_poll_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Next Poll At",
        help_text="When the poller should next check ClinVar for this batch.",
    )
    history = HistoricalRecords()

    objects: ClassVar[BatchManager] = BatchManager()

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        db_table = "batch"
        ordering = ["-added_at"]
        verbose_name = "Batch"
        verbose_name_plural = "Batches"

    def __str__(self) -> str:
        """Returns the batch's human-readable ID."""
        return self.slug

    def get_absolute_url(self) -> str:
        """Returns the batch's page."""
        return reverse("css:detail", kwargs={"slug": self.slug})

    @property
    def status_help(self) -> str:
        """What the batch's status means, in plain words, for its tooltip."""
        if self.status == self.Status.ERROR_AT_CLINVAR:
            by_code = self.ERROR_CODE_HELP.get(self.clinvar_error_code or 0)
            if by_code:
                return by_code
        return self.STATUS_HELP[self.status]


class Record(SlugModel):
    """One germline variant classification a client sent to the CSS.

    Each record is one variant-condition pair: its ClinVar JSON as the client sent it,
    and a copy of its fields, so pages and search can use them. It waits in the CSS
    until it's sent to ClinVar. Its slug is R and the start of its UUID, such as
    R3f2a9c1e.
    """

    slug_prefix = "R"

    class Status(models.TextChoices):
        """Where the record is, relative to the CSS's batches and ClinVar."""

        WAITING_FOR_BATCH = "waiting_for_batch", "Waiting"
        IN_BATCH = "in_batch", "In a Batch"
        SUCCEEDED_AT_CLINVAR = "succeeded_at_clinvar", "Success"
        WITHDRAWN = "withdrawn", "Withdrawn"

    # What each status means, for its tooltip. Success is ClinVar's word for a record
    # it accepted, from its summary report.
    STATUS_HELP: ClassVar[dict[str, str]] = {
        Status.WAITING_FOR_BATCH: (
            "The CSS has this record, and it's waiting to be added to a batch for "
            "ClinVar."
        ),
        Status.IN_BATCH: (
            "This record is in a batch that's been or is being sent to ClinVar."
        ),
        Status.SUCCEEDED_AT_CLINVAR: "ClinVar accepted this record.",
        Status.WITHDRAWN: "This record was withdrawn, so it won't be sent to ClinVar.",
    }

    api_key = models.ForeignKey(
        "ApiKey",
        blank=True,
        null=True,
        on_delete=models.PROTECT,
        related_name="records",
        verbose_name="Client",
        help_text="The API key of the client that sent the record.",
    )
    affiliation_id = models.PositiveIntegerField(
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Affiliation ID",
        help_text="The AS ID of the curation group whose classification this is.",
    )
    affiliation_name = models.CharField(
        blank=True,
        default="",
        max_length=255,
        verbose_name="Affiliation",
        help_text="The curation group's name, as the client sent it.",
    )
    payload = models.JSONField(
        blank=True,
        default=dict,
        verbose_name="Payload",
        help_text="The record's ClinVar JSON as the client sent it.",
    )
    status = models.CharField(
        choices=Status.choices,
        default=Status.WAITING_FOR_BATCH,
        max_length=32,
        verbose_name="Status",
        help_text="Where the record is, relative to the CSS's batches and ClinVar.",
    )
    record_status = models.CharField(
        choices=RecordStatus.choices,
        max_length=8,
        verbose_name="Record Status",
        help_text="Whether the record is new to ClinVar or updates one of its records.",
    )
    clinvar_accession = models.CharField(
        blank=True,
        default="",
        max_length=16,  # An SCV accession is of the form SCV000123456.
        verbose_name="ClinVar Accession",
        help_text="The record's SCV accession in ClinVar. Blank for a novel record.",
    )
    local_id = models.CharField(
        blank=True,
        default="",
        max_length=255,
        verbose_name="Local ID",
        help_text="The client's ID for the variant. ClinVar makes it public.",
    )
    local_key = models.CharField(
        blank=True,
        default="",
        max_length=255,
        verbose_name="Local Key",
        help_text="The client's ID for the variant-condition pair.",
    )
    submitted_assembly = models.CharField(
        choices=Assembly.choices,
        max_length=16,
        verbose_name="Assembly",
        help_text="The genome assembly the HGVS expression is on.",
    )
    hgvs = models.CharField(
        max_length=512,
        verbose_name="HGVS",
        help_text="The variant, as an HGVS expression.",
    )
    gene_symbol = models.CharField(
        blank=True,
        default="",
        max_length=32,
        verbose_name="Gene Symbol",
        help_text="The gene whose relationship to the condition supports the record.",
    )
    condition_db = models.CharField(
        choices=ConditionDb.choices,
        max_length=16,
        verbose_name="Condition Database",
        help_text="The database the condition's ID is from.",
    )
    condition_id = models.CharField(
        max_length=64,
        verbose_name="Condition ID",
        help_text="The condition's ID, such as MONDO:0011450.",
    )
    classification = models.CharField(
        choices=Classification.choices,
        max_length=32,
        verbose_name="Classification",
        help_text="The variant's classification for the condition.",
    )
    mode_of_inheritance = models.CharField(
        blank=True,
        choices=ModeOfInheritance.choices,
        default="",
        max_length=64,
        verbose_name="Mode of Inheritance",
        help_text="How the variant is inherited for this condition.",
    )
    date_last_evaluated = models.DateField(
        blank=True,
        null=True,
        verbose_name="Date Last Evaluated",
        help_text="When the variant was last classified.",
    )
    comment = models.TextField(
        blank=True,
        default="",
        verbose_name="Comment",
        help_text="Why the variant has its classification.",
    )
    allele_origin = models.CharField(
        choices=AlleleOrigin.choices,
        max_length=16,
        verbose_name="Allele Origin",
        help_text="Where the variant's allele came from.",
    )
    affected_status = models.CharField(
        choices=AffectedStatus.choices,
        max_length=16,
        verbose_name="Affected Status",
        help_text="Whether the individuals observed had the condition.",
    )
    collection_method = models.CharField(
        choices=CollectionMethod.choices,
        max_length=32,
        verbose_name="Collection Method",
        help_text="How the evidence for the classification was gathered.",
    )
    added_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Added At",
        help_text="When the CSS received the record.",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
        help_text="When the record was last updated.",
    )
    history = HistoricalRecords()

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        db_table = "record"
        ordering = ["local_id"]
        verbose_name = "Record"
        verbose_name_plural = "Records"

    def __str__(self) -> str:
        """Returns the record's variant and classification."""
        return f"{self.hgvs}: {self.classification}"

    @property
    def status_help(self) -> str:
        """What the record's status means, in plain words, for its tooltip."""
        return self.STATUS_HELP[self.status]


class BatchRecord(UUIDModel):
    """One attempt to send a record to ClinVar, in one batch.

    A record that fails in one batch can be tried again in a later one, so each attempt
    keeps its own result from ClinVar's summary report.
    """

    class Result(models.TextChoices):
        """ClinVar's processingStatus for the record, from its summary report."""

        SUCCESS = "Success", "Success"
        ERROR = "Error", "Error"

    batch = models.ForeignKey(
        Batch,
        on_delete=models.CASCADE,
        related_name="batch_records",
        verbose_name="Batch",
        help_text="The batch the record was sent in.",
    )
    record = models.ForeignKey(
        Record,
        on_delete=models.CASCADE,
        related_name="batch_records",
        verbose_name="Record",
        help_text="The record that was sent.",
    )
    position = models.PositiveIntegerField(
        verbose_name="Position",
        help_text="Where the record is in the batch's germlineSubmission, from 0.",
    )
    result = models.CharField(
        blank=True,
        choices=Result.choices,
        default="",
        max_length=8,
        verbose_name="Result",
        help_text="ClinVar's result for the record. Blank until ClinVar reports.",
    )
    scv = models.CharField(
        blank=True,
        default="",
        max_length=32,
        verbose_name="SCV",
        help_text="The SCV accession ClinVar gave the record, if it accepted it.",
    )
    errors = models.JSONField(
        blank=True,
        null=True,
        verbose_name="Errors",
        help_text="ClinVar's errors for the record, if any, for developers.",
    )
    added_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Added At",
        help_text="When the record was added to the batch.",
    )
    history = HistoricalRecords()

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        db_table = "batch_record"
        ordering = ["batch", "position"]
        verbose_name = "Batch Record"
        verbose_name_plural = "Batch Records"
        constraints: ClassVar[list[models.BaseConstraint]] = [
            models.UniqueConstraint(
                fields=["batch", "record"], name="batch_record_once_per_batch"
            ),
            models.UniqueConstraint(
                fields=["batch", "position"], name="batch_record_one_per_position"
            ),
        ]

    def __str__(self) -> str:
        """Returns the record's and batch's IDs."""
        return f"{self.record.slug} in {self.batch.slug}"


class AffiliationSettings(UUIDModel):
    """The ClinVar submission-level values staff set for one affiliation.

    ClinVar applies these to a whole submission, and a batch holds one affiliation's
    records, so a batch takes them from its affiliation's settings.
    """

    affiliation_id = models.PositiveIntegerField(
        unique=True,
        verbose_name="Affiliation ID",
        help_text="The AS ID of the curation group these settings are for.",
    )
    assertion_criteria_db = models.CharField(
        blank=True,
        choices=AssertionCriteriaDb.choices,
        default="",
        max_length=8,
        verbose_name="Assertion Criteria Database",
        help_text="Where the criteria used to classify the variants are published.",
    )
    assertion_criteria_id = models.CharField(
        blank=True,
        default="",
        max_length=255,
        verbose_name="Assertion Criteria ID",
        help_text="The criteria's ID in that database, such as a PubMed ID.",
    )
    behalf_org_id = models.PositiveIntegerField(
        blank=True,
        null=True,
        validators=[
            MinValueValidator(
                1,
                message=(
                    "Enter ClinVar's ID for the organization, a number of 1 or more."
                ),
            )
        ],
        verbose_name="On Behalf Of",
        help_text=(
            "ClinVar's ID for the organization the batches are made for, if it isn't "
            "the submitter."
        ),
    )
    release_status = models.CharField(
        blank=True,
        choices=ReleaseStatus.choices,
        default="",
        max_length=32,
        verbose_name="Release Status",
        help_text="Whether ClinVar may make the records public. Blank means public.",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Updated At",
        help_text="When the settings were last changed.",
    )
    history = HistoricalRecords()

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        db_table = "affiliation_settings"
        verbose_name = "Affiliation Settings"
        verbose_name_plural = "Affiliation Settings"

    def __str__(self) -> str:
        """Returns the affiliation's ID."""
        return f"Settings for affiliation {self.affiliation_id}"


def _hash(raw_key: str) -> str:
    """Returns the hash of an API key that's stored in place of the key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


class ApiKeyManager(models.Manager["ApiKey"]):
    def create_key(self, *, name: str) -> tuple["ApiKey", str]:
        """Creates an API key for a client.

        Args:
            name: The client's name, such as "GCI".

        Returns:
            The new key and its raw value, which is never stored or shown again.
        """
        api_key = self.model(name=name)
        raw_key = api_key.set_new_key()
        api_key.save()
        return api_key, raw_key

    def verify(self, raw_key: str) -> "ApiKey | None":
        """Returns the active key with this raw value, and records its use.

        Returns:
            The key, or None if no active key matches.
        """
        if not raw_key:
            return None
        api_key = self.filter(key_hash=_hash(raw_key), is_active=True).first()
        if api_key:
            # update() skips the history, which shouldn't get a row per request.
            now = timezone.now()
            self.filter(pk=api_key.pk).update(last_used_at=now)
            api_key.last_used_at = now
        return api_key


# Every raw key starts with this, so a leaked one is easy to recognize.
API_KEY_PREFIX = "css_"

# How much of a raw key is kept, so staff can tell keys apart.
PREFIX_LENGTH = 8


class ApiKey(UUIDModel):
    """The key one client system sends to use the CSS's API.

    Only a hash of the key is stored. Staff create keys in the Django admin, which shows
    the raw key once.
    """

    name = models.CharField(
        max_length=128,
        verbose_name="Client",
        help_text="The client system that uses this key, such as the GCI.",
    )
    prefix = models.CharField(
        editable=False,
        max_length=PREFIX_LENGTH,
        verbose_name="Prefix",
        help_text="The start of the key, so you can tell keys apart.",
    )
    key_hash = models.CharField(
        editable=False,
        max_length=64,
        unique=True,
        verbose_name="Key Hash",
        help_text="The SHA-256 hash of the key. The key itself isn't stored.",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Active",
        help_text="Whether the key can call the API. Turn it off to revoke the key.",
    )
    added_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Added At",
        help_text="When the key was created.",
    )
    last_used_at = models.DateTimeField(
        blank=True,
        null=True,
        editable=False,
        verbose_name="Last Used At",
        help_text="When the key last called the API.",
    )
    history = HistoricalRecords()

    objects: ClassVar[ApiKeyManager] = ApiKeyManager()

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        db_table = "api_key"
        ordering = ["name"]
        verbose_name = "API Key"
        verbose_name_plural = "API Keys"

    def set_new_key(self) -> str:
        """Gives the key a new random value, without saving it.

        Returns:
            The raw value, which is never stored or shown again.
        """
        raw_key = f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
        self.prefix = raw_key[:PREFIX_LENGTH]
        self.key_hash = _hash(raw_key)
        return raw_key

    def __str__(self) -> str:
        """Returns the client's name and the start of the key."""
        return f"{self.name} ({self.prefix}…)"
