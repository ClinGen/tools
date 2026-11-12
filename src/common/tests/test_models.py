"""Houses tests for the shared model helpers."""

import uuid

from django.test import TestCase

from common.models import make_slug


class MakeSlugTest(TestCase):
    def test_slug_is_the_prefix_and_eight_hex_characters(self):
        id_ = uuid.UUID("3f2a9c1e-0000-4000-8000-000000000000")
        self.assertEqual(make_slug("T", id_), "T3f2a9c1e")
