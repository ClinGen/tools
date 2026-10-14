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

    def test_prod_settings_require_a_secret_key(self):
        sys.modules.pop("config.settings.prod", None)
        with (
            mock.patch("config.settings.base.SECRET_KEY", None),
            self.assertRaises(ImproperlyConfigured),
        ):
            importlib.import_module("config.settings.prod")
