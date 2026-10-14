"""Provides production settings."""

from django.contrib import messages
from django.core.exceptions import ImproperlyConfigured

from .base import *  # ruff: ignore[undefined-local-with-import-star] (We want to import everything.)
from .base import BASE_DIR, SECRET_KEY

if not SECRET_KEY:
    error_message = "Set SECRET_KEY in the environment."
    raise ImproperlyConfigured(error_message)

DEBUG = False

ALLOWED_HOSTS = [
    "tools-test.clinicalgenome.org",
    "tools.clinicalgenome.org",
]

CSRF_COOKIE_SECURE = True

SESSION_COOKIE_SECURE = True

MESSAGE_LEVEL = messages.INFO

LOG_FILE_NAME = "tools.log"

LOG_DIR = BASE_DIR.parent / "logs"
if not LOG_DIR.exists():
    LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / LOG_FILE_NAME
if not LOG_FILE.exists():
    LOG_FILE.touch()

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {name} {message}",  # ruff: ignore[line-too-long]
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
        "file": {
            "level": "INFO",
            "class": "logging.handlers.RotatingFileHandler",
            "filename": LOG_FILE,
            "maxBytes": 1024 * 1024 * 5,  # 1024 * 1024 * 5 = 5 MB.
            "backupCount": 5,
            "formatter": "verbose",
        },
    },
    "root": {
        "handlers": ["console", "file"],
        "level": "INFO",
    },
}
