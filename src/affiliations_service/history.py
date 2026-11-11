"""Describes an object's change history in plain language for the AS's pages."""

from dataclasses import dataclass
from datetime import datetime
from typing import cast

from django.db import models

# Fields every model has that staff don't need to see changes to.
IGNORED_FIELDS = {"added_at", "updated_at"}


@dataclass(frozen=True)
class HistoryEntry:
    """One change to an object.

    Attributes:
        when: When the change was made.
        who: The email of the staff member who made it, or "" if unknown.
        changes: Sentences describing what changed.
    """

    when: datetime
    who: str
    changes: list[str]


def _display(field: models.Field, value: object) -> str:
    """Returns a field's value the way staff would read it."""
    if value is None or value == "":
        return "nothing"
    if isinstance(field, models.BooleanField):
        return "Yes" if value else "No"
    if field.choices:
        return str(dict(field.flatchoices).get(value, value))
    if isinstance(field, models.ForeignKey):
        manager = field.related_model._default_manager  # ruff: ignore[private-member-access]
        related = manager.filter(pk=value).first()
        return str(related) if related else "something that was removed"
    return str(value)


def describe_history(obj: models.Model, noun: str) -> list[HistoryEntry]:
    """Describes each change to an object, newest first.

    Args:
        obj: A model instance with `history = HistoricalRecords()`.
        noun: What to call the object, such as "the affiliation".

    Returns:
        One entry per historical record.
    """
    records = list(obj.history.select_related("history_user").order_by("history_date"))  # ty: ignore[unresolved-attribute] (simple_history adds history.)
    entries = []
    previous = None
    for record in records:
        if previous is None:
            changes = [f"Added {noun}."]
        else:
            delta = record.diff_against(previous, excluded_fields=IGNORED_FIELDS)
            changes = []
            for change in delta.changes:
                field = cast(
                    "models.Field",
                    obj._meta.get_field(change.field),  # ruff: ignore[private-member-access]
                )
                changes.append(
                    f"Changed {field.verbose_name} from {_display(field, change.old)} "
                    f"to {_display(field, change.new)}."
                )
        if changes:
            user = record.history_user
            entries.append(
                HistoryEntry(record.history_date, user.email if user else "", changes)
            )
        previous = record
    return entries[::-1]
