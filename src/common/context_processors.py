"""Houses context processors used throughout the app."""

from django.conf import settings


def git_sha(request) -> dict:  # ruff: ignore[missing-type-function-argument, unused-function-argument] (Required to have the param.)
    """Returns the shortened Git SHA."""
    return {"GIT_SHA": settings.GIT_SHA}


def env(request) -> dict:  # ruff: ignore[missing-type-function-argument, unused-function-argument] (Required to have the param.)
    """Returns the current environment name."""
    return {"ENV": settings.ENV}
