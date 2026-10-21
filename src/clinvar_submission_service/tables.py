from urllib.parse import urlencode

import django_tables2 as tables
from django.db.models import QuerySet
from django.template.loader import render_to_string
from django.utils.html import format_html, format_html_join

from clinvar_submission_service.models import Submission


class SubmissionTable(tables.Table):
    """The submissions list, one row per submission."""

    slug = tables.Column(verbose_name="ID", linkify=True)
    affiliation_name = tables.Column(verbose_name="Affiliation")
    variants = tables.Column(empty_values=(), orderable=False)
    api_key__name = tables.Column(verbose_name="Sent By")
    status = tables.Column(orderable=False)
    clinvar_submission_id = tables.Column(verbose_name="ClinVar ID")
    # When the CSS got the submission. ClinVar gets it when it's forwarded.
    added_at = tables.DateTimeColumn(verbose_name="Received by CSS", format="Y-m-d H:i")

    class Meta:
        attrs = {"class": "table is-fullwidth is-hoverable"}

    def __init__(
        self, data: QuerySet[Submission], *, affiliation: str = "", **kwargs: object
    ) -> None:
        """Makes the table.

        Args:
            data: The submissions.
            affiliation: The affiliation filter the list has, if any, which each status
                tag's link keeps.
            **kwargs: Passed to django-tables2's Table.
        """
        super().__init__(data, **kwargs)
        self.affiliation = affiliation

    def render_affiliation_name(self, value: str, record: Submission) -> str:
        """Returns the affiliation, linked to the list of its submissions."""
        if record.affiliation_id is None:
            return value
        return format_html(
            '<a href="?affiliation={}">{}</a>', record.affiliation_id, value
        )

    def render_status(self, record: Submission) -> str:
        """Returns the status tag, linked to the list of submissions in that status."""
        params = {"affiliation": self.affiliation, "status": record.status}
        query = urlencode({name: value for name, value in params.items() if value})
        return render_to_string(
            "clinvar_submission_service/partials/status.html",
            {"submission": record, "href": f"?{query}"},
        )

    def render_variants(self, record: Submission) -> str:
        """Returns each record's gene, or its HGVS if it has no gene."""
        records = record.records.all()  # type: ignore
        return format_html_join(
            ", ", "{}", ((r.gene_symbol or r.hgvs,) for r in records)
        )
