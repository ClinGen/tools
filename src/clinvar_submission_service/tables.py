from urllib.parse import urlencode

import django_tables2 as tables
from django.db.models import QuerySet
from django.template.loader import render_to_string
from django.utils.html import format_html, format_html_join

from clinvar_submission_service.models import Batch, Classification, Record


class BatchTable(tables.Table):
    """The batches list, one row per batch."""

    slug = tables.Column(verbose_name="ID", linkify=True)
    affiliation_name = tables.Column(verbose_name="Affiliation")
    variants = tables.Column(empty_values=(), orderable=False)
    api_key__name = tables.Column(verbose_name="Sent By")
    status = tables.Column(orderable=False)
    clinvar_submission_id = tables.Column(verbose_name="ClinVar ID")
    # When the CSS got the batch. ClinVar gets it when it's forwarded.
    added_at = tables.DateTimeColumn(verbose_name="Received by CSS", format="Y-m-d H:i")

    class Meta:
        attrs = {"class": "table is-fullwidth is-hoverable"}

    def __init__(
        self, data: QuerySet[Batch], *, affiliation: str = "", **kwargs: object
    ) -> None:
        """Makes the table.

        Args:
            data: The batches.
            affiliation: The affiliation filter the list has, if any, which each status
                tag's link keeps.
            **kwargs: Passed to django-tables2's Table.
        """
        super().__init__(data, **kwargs)
        self.affiliation = affiliation

    def render_affiliation_name(self, value: str, record: Batch) -> str:
        """Returns the affiliation, linked to the list of its batches."""
        if record.affiliation_id is None:
            return value
        return format_html(
            '<a href="?affiliation={}">{}</a>', record.affiliation_id, value
        )

    def render_status(self, record: Batch) -> str:
        """Returns the status tag, linked to the list of batches in that status."""
        params = {"affiliation": self.affiliation, "status": record.status}
        query = urlencode({name: value for name, value in params.items() if value})
        return render_to_string(
            "clinvar_submission_service/partials/status.html",
            {"batch": record, "href": f"?{query}"},
        )

    def render_variants(self, record: Batch) -> str:
        """Returns each record's gene, or its HGVS if it has no gene."""
        records = record.records.all()
        return format_html_join(
            ", ", "{}", ((r.gene_symbol or r.hgvs,) for r in records)
        )


class RecordTable(tables.Table):
    """The records list, one row per record."""

    slug = tables.Column(verbose_name="ID", linkify=True)
    local_id = tables.Column(verbose_name="Local ID")
    affiliation_name = tables.Column(verbose_name="Affiliation")
    variant = tables.Column(empty_values=(), orderable=False)
    classification = tables.Column()
    status = tables.Column(orderable=False)
    added_at = tables.DateTimeColumn(verbose_name="Received by CSS", format="Y-m-d H:i")

    class Meta:
        attrs = {"class": "table is-fullwidth is-hoverable"}

    def __init__(
        self, data: QuerySet[Record], *, affiliation: str = "", **kwargs: object
    ) -> None:
        """Makes the table.

        Args:
            data: The records.
            affiliation: The affiliation filter the list has, if any, which each status
                tag's link keeps.
            **kwargs: Passed to django-tables2's Table.
        """
        super().__init__(data, **kwargs)
        self.affiliation = affiliation

    def render_affiliation_name(self, value: str, record: Record) -> str:
        """Returns the affiliation, linked to the list of its records."""
        if record.affiliation_id is None:
            return value
        return format_html(
            '<a href="?affiliation={}">{}</a>', record.affiliation_id, value
        )

    def render_variant(self, record: Record) -> str:
        """Returns the record's gene, if it has one, above its HGVS."""
        if record.gene_symbol:
            return format_html(
                "<strong>{}</strong><br>{}", record.gene_symbol, record.hgvs
            )
        return record.hgvs

    def render_classification(self, record: Record) -> str:
        """Returns the classification in ClinVar's capitalization."""
        return str(Classification(record.classification).label)

    def render_status(self, record: Record) -> str:
        """Returns the status tag, linked to the list of records in that status."""
        params = {"affiliation": self.affiliation, "status": record.status}
        query = urlencode({name: value for name, value in params.items() if value})
        return render_to_string(
            "clinvar_submission_service/partials/record_status.html",
            {"record": record, "href": f"?{query}"},
        )
