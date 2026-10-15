"""Provides test settings."""

import sentry_sdk

from .dev import *  # ruff: ignore[undefined-local-with-import-star]
from .dev import BASE_DIR, DATABASES, STORAGES

# Disable Sentry during tests so they never send events or flush in the background.
sentry_sdk.init()

# Django gives SQLite an in-memory test database by default, and an in-memory database
# can't use WAL mode. A file-backed test database runs with the same journal mode as the
# real one. pytest-django gives each xdist worker its own copy.
DATABASES["default"]["TEST"] = {"NAME": BASE_DIR / "test_tools.db"}

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
