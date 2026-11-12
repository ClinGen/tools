"""Houses tests for the list of tools."""

from django.test import TestCase

from core.tools import get_tool


class GetToolTest(TestCase):
    def test_returns_the_tool_with_the_namespace(self):
        self.assertEqual(get_tool("ets").abbreviation, "ETS")

    def test_unknown_namespace_is_an_error(self):
        with self.assertRaises(LookupError):
            get_tool("nope")
