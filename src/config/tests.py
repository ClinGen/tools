import importlib
import sys
from io import StringIO
from types import ModuleType
from unittest import mock

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import SimpleTestCase


class SettingsTest(SimpleTestCase):
    # The system check asks the database whether it supports JSON fields.
    databases = {"default"}

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


class BackupSettingsTest(SimpleTestCase):
    def _load_base(self, **env: str) -> ModuleType:
        sys.modules.pop("config.settings.base", None)
        # Reloading the module re-runs sentry_sdk.init(), which must not turn Sentry
        # back on during tests.
        with (
            mock.patch.dict("os.environ", env, clear=False),
            mock.patch("sentry_sdk.init"),
        ):
            module = importlib.import_module("config.settings.base")
            sys.modules.pop("config.settings.base", None)
            importlib.import_module("config.settings.base")
        return module

    def test_backups_go_to_s3_when_a_bucket_is_set(self):
        base = self._load_base(DBBACKUP_BUCKET_NAME="tools-backups-test-123")
        storage = base.STORAGES["dbbackup"]
        assert storage["BACKEND"] == "storages.backends.s3.S3Storage"
        assert storage["OPTIONS"]["bucket_name"] == "tools-backups-test-123"

    def test_subdomain_defaults_to_dev(self):
        base = self._load_base(SUBDOMAIN="")
        assert base.SUBDOMAIN == "dev"
