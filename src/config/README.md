# `config`

This directory is the Django configuration package for ClinGen Tools. It holds the root
URL routing, the WSGI entry point, and layered settings for the base, development,
production, and test environments. Every tool shares these settings.

### `__init__.py`

Empty file that marks `config` as a Python package.

### `settings/__init__.py`

Empty file that marks `settings` as a Python package.

### `settings/base.py`

Defines settings shared across all environments: installed apps, middleware, templates,
the shared SQLite database (`tools.db`), static files served by WhiteNoise, and Clerk
sign-in through `auth_.backends.ClerkBackend`. The database runs in WAL mode with a busy
timeout and `IMMEDIATE` transactions, because background processes write to it alongside
the web process. Reads `SECRET_KEY`, `ENV`, `CLERK_SECRET_KEY`, and
`CLERK_PUBLISHABLE_KEY` from the environment.

### `settings/dev.py`

Extends `base.py` for local development: `DEBUG = True`, an insecure fallback
`SECRET_KEY` when none is set, `MESSAGE_LEVEL` set to `DEBUG`, and console logging.

### `settings/prod.py`

Extends `base.py` for the servers: refuses to start without `SECRET_KEY` or the Clerk
keys, sets `DEBUG = False`, restricts `ALLOWED_HOSTS` to tools-test.clinicalgenome.org
and tools.clinicalgenome.org, marks the CSRF and session cookies secure, and logs to the
console and a rotating file in `logs/` (5 MB, 5 backups).

### `settings/test.py`

Extends `dev.py` for test runs. Uses a file-backed test database so tests run in WAL
mode like the real database, uses plain static file storage so tests don't need
`collectstatic`, and silences logging so pytest shows logs only for failing tests.

### `tests.py`

Checks that the test settings load, that Django's system check passes, and that the
production settings refuse to load without each of their secrets.

### `urls.py`

Defines the project-level URL configuration. Routes the landing page, the Django admin,
and the sign-in views under `/auth/`.

### `wsgi.py`

Configures the WSGI application entry point. Loads environment variables from the
`.env` file via `python-dotenv` before initializing the Django application.
