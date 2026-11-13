"""Houses abstract base models that every tool's models extend.

Every model in ClinGen Tools has a UUID primary key, from `UUIDModel`. A model that
staff refer to by ID extends `SlugModel` instead, which adds a short human-readable
slug: the model's prefix letter and the first 8 hex characters of its UUID, like a
short Git hash.
"""

import uuid
from collections.abc import Sequence
from typing import ClassVar

from django.db import models

SLUG_HEX_LENGTH = 8


def make_slug(prefix: str, id_: uuid.UUID) -> str:
    """Returns a human-readable slug for an object.

    Args:
        prefix: The model's prefix letter, such as "T".
        id_: The object's UUID.

    Returns:
        The prefix followed by the first 8 hex characters of the UUID.
    """
    return f"{prefix}{id_.hex[:SLUG_HEX_LENGTH]}"


class UUIDModel(models.Model):
    """Gives a model a random UUID primary key instead of an auto-incrementing one."""

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        verbose_name="ID",
    )

    class Meta:
        """Provides metadata."""

        abstract = True


class SlugModel(UUIDModel):
    """Gives a model a UUID primary key and a short slug built from it.

    Set `slug_prefix` to the model's prefix letter. The slug is set on the first save.
    If another object already has it, the object gets a new UUID and slug.
    """

    slug_prefix: ClassVar[str] = ""

    slug = models.SlugField(
        default="",
        editable=False,
        max_length=16,
        unique=True,
        verbose_name="Human-Readable ID",
        help_text="The human-readable ID for the object.",
    )

    class Meta:  # ty: ignore[invalid-attribute-override] (Each Django model declares its own Meta.)
        """Provides metadata."""

        abstract = True

    def save(self, *args, **kwargs) -> None:
        """Adds a human-readable ID that no other object of this model has."""
        if not self.slug:
            self.slug = make_slug(self.slug_prefix, self.id)
            while type(self).objects.filter(slug=self.slug).exists():
                self.id = uuid.uuid4()
                self.slug = make_slug(self.slug_prefix, self.id)
        super().save(*args, **kwargs)

    @classmethod
    def set_unique_slugs(cls, objects: Sequence["SlugModel"]) -> None:
        """Gives unsaved objects slugs that no other object has, for bulk_create().

        bulk_create() skips save(), so it doesn't set slugs. An object whose slug is
        taken, by a saved object or an earlier one in the list, gets a new UUID, as in
        save(). Each round checks the database once.

        Args:
            objects: Unsaved objects of this model.
        """
        taken: set[str] = set()
        pending = list(objects)
        while pending:
            for obj in pending:
                obj.slug = make_slug(cls.slug_prefix, obj.id)
            saved = set(
                cls.objects.filter(slug__in=[obj.slug for obj in pending]).values_list(
                    "slug", flat=True
                )
            )
            retry = []
            for obj in pending:
                if obj.slug in saved or obj.slug in taken:
                    obj.id = uuid.uuid4()
                    retry.append(obj)
                else:
                    taken.add(obj.slug)
            pending = retry
