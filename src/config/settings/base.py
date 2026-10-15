"""Provides settings common to every environment."""

import os
from pathlib import Path
from typing import Any

import sentry_sdk

# We use Sentry for error monitoring and tracing. Events from a tool's pages are tagged
# with the tool by common.middleware.ToolTagMiddleware.
sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN"),
    environment=os.getenv("SENTRY_ENV"),
    send_default_pii=True,
    traces_sample_rate=1.0,
)

BASE_DIR = Path(__file__).resolve().parent.parent.parent

try:
    version_file_path = Path(BASE_DIR / "version.txt")
    with version_file_path.open(encoding="utf-8") as f:
        GIT_SHA = f.read().strip()
except FileNotFoundError:
    GIT_SHA = "dev"

SECRET_KEY = os.getenv("SECRET_KEY")

ENV = os.getenv("ENV", "dev")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "whitenoise.runserver_nostatic",
    "django.contrib.staticfiles",
    "simple_history",
    "dbbackup",
    "auth_",
    "common",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "simple_history.middleware.HistoryRequestMiddleware",
    "common.middleware.ToolTagMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "common.context_processors.git_sha",
                "common.context_processors.env",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

# Every tool shares this database, and background processes such as the CSS's poller
# write to it alongside the web process. WAL mode lets reads continue during a write,
# and the timeout makes a writer wait for the lock instead of failing right away.
# IMMEDIATE transactions take the write lock up front, so a read that later becomes a
# write can't fail with "database is locked" partway through.
DATABASES: dict[str, dict[str, Any]] = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "tools.db",
        "OPTIONS": {
            "init_command": "PRAGMA journal_mode=WAL;",
            "transaction_mode": "IMMEDIATE",
            "timeout": 20,
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",  # ruff: ignore[line-too-long]
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

AUTHENTICATION_BACKENDS = [
    "auth_.backends.ClerkBackend",
    "django.contrib.auth.backends.ModelBackend",
]

CLERK_SECRET_KEY = os.environ["CLERK_SECRET_KEY"]
CLERK_PUBLISHABLE_KEY = os.environ["CLERK_PUBLISHABLE_KEY"]

LOGIN_URL = "/auth/login"

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"

STATICFILES_DIRS = [BASE_DIR / "static"]

STATIC_ROOT = BASE_DIR / "public"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Servers keep database backups in S3. Without a bucket, as in dev and CI, backups go
# to a backups/ directory next to src/. boto3 reads the AWS_ACCESS_KEY_ID and
# AWS_SECRET_ACCESS_KEY environment variables itself.
DBBACKUP_BUCKET_NAME = os.getenv("DBBACKUP_BUCKET_NAME")

if DBBACKUP_BUCKET_NAME:
    BACKUP_STORAGE = {
        "BACKEND": "storages.backends.s3.S3Storage",
        "OPTIONS": {
            "bucket_name": DBBACKUP_BUCKET_NAME,
            "region_name": "us-west-2",
            "default_acl": None,
        },
    }
else:
    BACKUP_STORAGE = {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": BASE_DIR.parent / "backups"},
    }

STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
    "dbbackup": BACKUP_STORAGE,
}

# The server's subdomain: tools, tools-test, or dev on a developer's machine. Backup
# names use it, so you can tell prod and test apart. An empty value, as in a .env copied
# from .env.example, means dev too.
SUBDOMAIN = os.getenv("SUBDOMAIN") or "dev"

# Backups named by django-dbbackup go under daily/. Other backups, such as the one each
# deploy takes before it migrates, pass their own name with -o.
DBBACKUP_HOSTNAME = SUBDOMAIN

DBBACKUP_FILENAME_TEMPLATE = "daily/{servername}-{datetime}.{extension}"
