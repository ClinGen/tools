# `config`

This directory is the Django configuration package for ClinGen Tools. It holds the root
URL routing, the WSGI entry point, and layered settings for the base, development,
production, and test environments. Every tool shares these settings.

### `__init__.py`

Empty file that marks `config` as a Python package.

### `settings/__init__.py`

Empty file that marks `settings` as a Python package.

### `settings/base.py`

Defines settings shared across all environments: Sentry, installed apps, middleware,
templates, the shared SQLite database (`tools.db`), static files served by WhiteNoise,
Clerk sign-in through `auth_.backends.ClerkBackend`, UUID history IDs, and database
backups. The database runs in WAL mode with a busy timeout and `IMMEDIATE` transactions,
because background processes write to it alongside the web process. Backups go to the S3
bucket named by `DBBACKUP_BUCKET_NAME`, or to `backups/` next to `src/` when it's empty,
and their names start with `SUBDOMAIN`. Reads `SECRET_KEY`, `ENV`, the Sentry settings,
and the backup settings from the environment, and, as in the HCI, requires
`CLERK_SECRET_KEY` and `CLERK_PUBLISHABLE_KEY` in every environment. Also reads the
ETS's AWS settings and `ETS_DRY_RUN`, which is on unless it's set to `0`, and the CSS's
ClinVar key and endpoint, which defaults to ClinVar's test endpoint. Sets how often the
CSS's poller checks ClinVar, and raises `DATA_UPLOAD_MAX_MEMORY_SIZE` to 64 MB for the
CSS's largest submissions; Caddy keeps other paths at 2.5 MB. It also holds the old AS's
API URL and key (`AS_API_KEY`), which `import_old_as` uses.

### `settings/dev.py`

Extends `base.py` for local development: `DEBUG = True`, an insecure fallback
`SECRET_KEY` when none is set, `MESSAGE_LEVEL` set to `DEBUG`, and console logging that
suppresses noisy `httpcore` and `urllib3` debug output from Clerk and Sentry. It's the
only settings module that reads `CSS_SIMULATE_CLINVAR`, which turns on the CSS's
simulated ClinVar when it's 1; `base.py` sets it off, so prod can't simulate. While it's
on, the poller checks every few seconds instead of every few minutes, so a simulated
batch moves while you watch.

### `settings/prod.py`

Extends `base.py` for the servers: refuses to start without `SECRET_KEY`, sets
`DEBUG = False`, restricts `ALLOWED_HOSTS` to tools-test.clinicalgenome.org and
tools.clinicalgenome.org, marks the CSRF and session cookies secure, and logs to the
console and a rotating file in `logs/` (5 MB, 5 backups).

### `settings/test.py`

Extends `dev.py` for test runs. Turns Sentry off, uses a file-backed test database so
tests run in WAL mode like the real database, uses plain static file storage so tests
don't need `collectstatic`, never gives the CSS a real ClinVar key or the production
endpoint, turns the simulated ClinVar off and keeps `base.py`'s poll delays even if
`.env` turns simulating on, and silences logging so pytest shows logs only for failing
tests.

### `tests/__init__.py`

Marks `tests` as a Python package.

### `tests/test_settings.py`

Checks that the test settings load, that Django's system check passes, that the
production settings refuse to load without a `SECRET_KEY`, that backups go to S3 when a
bucket is set and to a local directory otherwise, that backup names start with the
subdomain, that the subdomain defaults to `dev`, that the ClinVar URL defaults to
ClinVar's test endpoint, and that only `0` turns the ETS's dry run off.

### `urls.py`

Defines the project-level URL configuration. Routes the landing page, the Django admin,
the sign-in views under `/auth/`, the AS under `/as/`, the CSS under `/css/`, and the
ETS under `/ets/`.

### `wsgi.py`

Configures the WSGI application entry point. Loads environment variables from the `.env`
file via `python-dotenv` before initializing the Django application.
