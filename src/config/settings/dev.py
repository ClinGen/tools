"""Provides development settings."""

import os
from datetime import timedelta

from django.contrib import messages

from .base import *  # ruff: ignore[undefined-local-with-import-star] (We want to import everything.)
from .base import SECRET_KEY

DEBUG = True

ALLOWED_HOSTS: list[str] = []

# A missing key is fine on a laptop. The prod settings refuse to start without one.
SECRET_KEY = SECRET_KEY or "django-insecure-dev-key"  # ruff: ignore[hardcoded-password-string]

MESSAGE_LEVEL = messages.DEBUG

# Answer the CSS's ClinVar requests with a simulated ClinVar. See
# clinvar_submission_service/simulation.py.
CSS_SIMULATE_CLINVAR = os.getenv("CSS_SIMULATE_CLINVAR") == "1"
if CSS_SIMULATE_CLINVAR:
    # Poll often, so a simulated batch moves while you watch.
    CSS_FIRST_POLL_DELAY = timedelta(seconds=10)
    CSS_POLL_MIN_DELAY = timedelta(seconds=10)
    CSS_POLL_MAX_DELAY = timedelta(minutes=1)
    CSS_POLL_SLEEP_SECONDS = 5

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "simple": {
            "format": "{levelname} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "simple",
        },
    },
    "loggers": {
        # httpcore generates per-connection DEBUG noise for every Clerk and Sentry
        # HTTP call (connect_tcp.started, start_tls.complete, etc.). Suppress it.
        "httpcore": {"level": "WARNING"},
        # urllib3 generates per-request DEBUG lines for every Sentry envelope POST.
        "urllib3": {"level": "WARNING"},
    },
    "root": {
        "handlers": ["console"],
        "level": "DEBUG",
    },
}
