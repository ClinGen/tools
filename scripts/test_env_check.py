"""Tests env_check.py, which checks that .env and .env.example have the same keys."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from env_check import main, read_keys


class EnvCheckTest(TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.env = Path(tmp.name) / ".env"
        self.example = Path(tmp.name) / ".env.example"

    def check(self, env: str | None, example: str) -> tuple[int, str]:
        """Write the two files, run the check, and return its exit code and output.

        Args:
            env: The text of .env, or None to leave .env missing.
            example: The text of .env.example.

        Returns:
            The exit code and what the check printed.
        """
        if env is not None:
            self.env.write_text(env, encoding="utf-8")
        self.example.write_text(example, encoding="utf-8")
        out = StringIO()
        with redirect_stdout(out):
            code = main(["--env", str(self.env), "--example", str(self.example)])
        return code, out.getvalue()

    def test_read_keys_skips_comments_and_blank_lines(self):
        self.env.write_text("# A comment\n\nSECRET_KEY=abc\n  # Indented\n")
        self.assertEqual(read_keys(self.env), {"SECRET_KEY"})

    def test_read_keys_handles_export_and_values_with_equals_signs(self):
        self.env.write_text("export SENTRY_DSN=https://x?a=b\nENV = dev\n")
        self.assertEqual(read_keys(self.env), {"SENTRY_DSN", "ENV"})

    def test_matching_keys_pass(self):
        code, out = self.check("A=1\nB=2\n", "B=\nA=\n")
        self.assertEqual(code, 0)
        self.assertIn("same keys", out)

    def test_key_only_in_env_fails(self):
        code, out = self.check("A=1\nNEW_KEY=2\n", "A=\n")
        self.assertEqual(code, 1)
        self.assertIn(f"Missing from {self.example}", out)
        self.assertIn("NEW_KEY", out)

    def test_key_only_in_example_fails(self):
        code, out = self.check("A=1\n", "A=\nOLD_KEY=\n")
        self.assertEqual(code, 1)
        self.assertIn(f"Missing from {self.env}", out)
        self.assertIn("OLD_KEY", out)

    def test_missing_file_fails_with_a_clear_message(self):
        code, out = self.check(None, "A=\n")
        self.assertEqual(code, 1)
        self.assertIn(f"{self.env} doesn't exist", out)
