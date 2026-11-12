"""Defines the django-tables2 tables for the AS's lists, which page like the HCI's."""

import django_tables2 as tables
from django.urls import reverse
from django.utils.html import format_html

from affiliations_service.models import CDWG, Affiliation, User

# How many rows each list shows per page.
PER_PAGE = 100

TABLE_ATTRS = {"class": "table is-fullwidth is-hoverable"}


class AffiliationTable(tables.Table):
    """The affiliation list, one row per affiliation."""

    affiliation_id = tables.Column(verbose_name="Affiliation ID")
    expert_panel_id = tables.Column(verbose_name="Expert Panel ID", default="")
    full_name = tables.Column(verbose_name="Name", linkify=True)
    type = tables.Column(verbose_name="Type")
    status = tables.TemplateColumn(
        template_code=(
            '{% include "affiliations_service/partials/status.html" '
            "with affiliation=record %}"
        ),
        verbose_name="Status",
    )
    cdwg = tables.Column(
        verbose_name="CDWG", accessor="cdwg__name", order_by="cdwg__name"
    )

    class Meta:
        """Provides metadata."""

        model = Affiliation
        fields = [
            "affiliation_id",
            "expert_panel_id",
            "full_name",
            "type",
            "status",
            "cdwg",
        ]
        attrs = TABLE_ATTRS


class UserTable(tables.Table):
    """The user list, one row per user."""

    name = tables.Column(verbose_name="Name", linkify=True)
    email = tables.Column(verbose_name="Email")
    institution = tables.Column(verbose_name="Institution")

    class Meta:
        """Provides metadata."""

        model = User
        fields = ["name", "email", "institution"]
        attrs = TABLE_ATTRS


class CdwgTable(tables.Table):
    """The CDWG list, with each CDWG's affiliation count and an edit link."""

    name = tables.Column(verbose_name="Name")
    affiliation_count = tables.Column(verbose_name="Affiliations")
    edit = tables.TemplateColumn(
        template_code=(
            "<a href=\"{% url 'as:cdwg-edit' pk=record.pk %}\" "
            'aria-label="Edit {{ record.name }}" title="Edit {{ record.name }}">'
            '<i class="bi bi-pencil-square" aria-hidden="true"></i></a>'
        ),
        verbose_name="Edit",
        orderable=False,
        empty_values=(),
    )

    class Meta:
        """Provides metadata."""

        model = CDWG
        fields = ["name", "affiliation_count", "edit"]
        attrs = TABLE_ATTRS

    def render_affiliation_count(self, value: int, record: CDWG) -> str:
        """Returns the count, linked to the affiliation list filtered by the CDWG."""
        return format_html(
            '<a href="{}?cdwg={}">{}</a>', reverse("as:index"), record.pk, value
        )
