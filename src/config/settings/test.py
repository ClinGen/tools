"""Provides test settings."""

from .dev import *  # ruff: ignore[undefined-local-with-import-star]
from .dev import BASE_DIR, DATABASES

# Django gives SQLite an in-memory test database by default, and an in-memory database
# can't use WAL mode. A file-backed test database runs with the same journal mode as the
# real one. pytest-django gives each xdist worker its own copy.
DATABASES["default"]["TEST"] = {"NAME": BASE_DIR / "test_tools.db"}

# Tests don't need the manifest that collectstatic builds.
STORAGES = {
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
    "root": {
        "handlers": ["null"],
    },
}
