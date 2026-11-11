"""Holds helpers that the AS's API endpoints share."""

from typing import Any

from django.db import models, transaction


def save_validated(obj: models.Model, changes: dict[str, Any] | None = None) -> None:
    """Applies changes to a model instance, checks its rules, and saves it.

    If the instance breaks a rule, `full_clean()` raises a `ValidationError`, which
    the API turns into a 400.

    Args:
        obj: The instance to save.
        changes: Field values to set first, if any.
    """
    for field, value in (changes or {}).items():
        setattr(obj, field, value)
    with transaction.atomic():
        obj.full_clean()
        obj.save()
