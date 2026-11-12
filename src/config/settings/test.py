"""Provides test settings."""

from datetime import timedelta

import sentry_sdk

from .dev import *  # ruff: ignore[undefined-local-with-import-star]
from .dev import BASE_DIR, DATABASES, STORAGES

# Disable Sentry during tests so they never send events or flush in the background.
sentry_sdk.init()

# Django gives SQLite an in-memory test database by default, and an in-memory database
# can't use WAL mode. A file-backed test database runs with the same journal mode as the
# real one. pytest-django gives each xdist worker its own copy.
DATABASES["default"]["TEST"] = {"NAME": BASE_DIR / "test_tools.db"}

# Tests never use a real ClinVar key or the production endpoint, even if .env has them.
# The contract tests read their key from the environment themselves.
CSS_CLINVAR_API_URL = "https://submit.ncbi.nlm.nih.gov/apitest/v1"
CSS_CLINVAR_API_KEY = ""

# Tests turn the simulated ClinVar on themselves, even if .env turns it on for dev, and
# keep base.py's poll delays, which dev.py shortens while simulating.
CSS_SIMULATE_CLINVAR = False
CSS_FIRST_POLL_DELAY = timedelta(minutes=5)
CSS_POLL_SLEEP_SECONDS = 60
CSS_POLL_MIN_DELAY = timedelta(minutes=5)
CSS_POLL_MAX_DELAY = timedelta(hours=6)

# Tests don't need the manifest that collectstatic builds.
STORAGES = {
    **STORAGES,
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Replace dev.py's console StreamHandler with a null handler so logs don't print to
# stderr during test runs. pytest shows captured logs only for failing tests.
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "null": {
            "class": "logging.NullHandler",
        },
    },
    "loggers": {
        # Suppress asyncio DEBUG logs that fire during Clerk SDK's process-exit
        # finalizer; without this the finalizer triggers a log write after
        # pytest-xdist has already closed its capture stream, printing
        # "--- Logging error ---" to the terminal after every worker exits.
        "asyncio": {"level": "WARNING"},
    },
    "root": {
        "handlers": ["null"],
    },
}
