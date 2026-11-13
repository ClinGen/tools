"""Houses tests for the settings."""

import importlib
import sys
from io import StringIO
from types import ModuleType
from unittest import mock

from django.conf import global_settings, settings
from django.core.exceptions import ImproperlyConfigured
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase


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

    def test_request_bodies_use_djangos_default_limit(self):
        self.assertEqual(
            settings.DATA_UPLOAD_MAX_MEMORY_SIZE,
            global_settings.DATA_UPLOAD_MAX_MEMORY_SIZE,
        )

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

    def test_the_clinvar_url_defaults_to_clinvars_test_endpoint(self):
        base = self._load_base(CSS_CLINVAR_API_URL="")
        assert base.CSS_CLINVAR_API_URL == "https://submit.ncbi.nlm.nih.gov/apitest/v1"

    def test_only_zero_turns_the_ets_dry_run_off(self):
        assert self._load_base(ETS_DRY_RUN="0").ETS_DRY_RUN is False
        for value in ["", "1", "false", "off"]:
            assert self._load_base(ETS_DRY_RUN=value).ETS_DRY_RUN is True


class BackupStorageTest(TestCase):
    def test_backups_go_to_a_local_directory_without_a_bucket(self):
        storage = settings.STORAGES["dbbackup"]
        self.assertEqual(
            storage["BACKEND"], "django.core.files.storage.FileSystemStorage"
        )
        self.assertEqual(
            storage["OPTIONS"]["location"], settings.BASE_DIR.parent / "backups"
        )

    def test_backup_names_start_with_the_subdomain(self):
        self.assertEqual(settings.DBBACKUP_HOSTNAME, settings.SUBDOMAIN)
        self.assertTrue(
            settings.DBBACKUP_FILENAME_TEMPLATE.startswith("daily/{servername}-")
        )
