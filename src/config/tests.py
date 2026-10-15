import importlib
import sys
from io import StringIO
from unittest import mock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import SimpleTestCase


class SettingsTest(SimpleTestCase):
    def test_test_settings_are_loaded(self):
        assert settings.SETTINGS_MODULE == "config.settings.test"
        assert settings.SECRET_KEY

    def test_system_check_passes(self):
        out = StringIO()
        call_command("check", stdout=out)
        assert "no issues" in out.getvalue()

    def test_prod_settings_require_their_secrets(self):
        for name in ["SECRET_KEY", "CLERK_SECRET_KEY", "CLERK_PUBLISHABLE_KEY"]:
            with self.subTest(name=name):
                sys.modules.pop("config.settings.prod", None)
                with (
                    mock.patch.multiple(
                        "config.settings.base",
                        SECRET_KEY="secret",  # ruff: ignore[hardcoded-password-func-arg]
                        CLERK_SECRET_KEY="sk_test",  # ruff: ignore[hardcoded-password-func-arg]
                        CLERK_PUBLISHABLE_KEY="pk_test",
                    ),
                    mock.patch(f"config.settings.base.{name}", ""),
                    self.assertRaisesMessage(ImproperlyConfigured, name),
                ):
                    importlib.import_module("config.settings.prod")
