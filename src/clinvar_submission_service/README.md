# `clinvar_submission_service`

This app is the ClinVar Submission Service (CSS), mounted at `/css/` with the URL
namespace `css`. It forwards ClinGen clients' submissions to ClinVar and tracks each one
until ClinVar has processed it. Only users with `has_css_permissions` can use its pages.
"The ClinVar Submission Service" in `docs/design.md` describes how a submission moves
through the CSS.

### `__init__.py`

Empty file that marks `clinvar_submission_service` as a Python package.

### `admin.py`

Registers `Submission` and `ApiKey` in the Django admin, with their history. A
submission's ClinVar fields are read-only, since only ClinVar's responses should change
them. Adding an API key generates its value and shows it once, in a warning message;
after that, only its prefix is shown.

### `api.py`

Serves the CSS's API, version 1, as a Django Ninja `NinjaAPI` at `/css/api/v1/`, with
OpenAPI docs at `/css/api/v1/docs`. Every endpoint needs an API key (see `api_auth.py`),
and a client sees only its own submissions. `POST /submissions` saves the ClinVar
content as a submission and forwards it, `GET /submissions` lists the client's
submissions a page at a time, and `GET /submissions/{slug}` reads one with ClinVar's
responses. Content with more than 10,000 records gets a 422.

### `api_auth.py`

Defines `ApiKeyAuth`, the Ninja auth class for the CSS's API. It reads the key from the
`X-API-Key` header and accepts it only if it's an active `ApiKey`, which becomes
`request.auth`.

### `apps.py`

Configures the `clinvar_submission_service` app.

### `clients.py`

Wraps the NCBI ClinVar Submission API in `ClinVarClient`, built on requests, with one
method for each call the CSS makes: create a submission (or a dry run), read its status,
and download its summary report. Every request sends the `SP-API-KEY` header and a
timeout. A failed request raises `ClinVarError`, which says whether it's worth retrying
(timeouts, 429s, and 5xx are; 400s and 401s aren't) and carries a 429's `Retry-After`.
Nothing it logs or raises includes the API key. `ClinVarClient.from_settings()` builds
one from the `CSS_` settings and raises `ImproperlyConfigured` without a key.

### `fakes.py`

Defines `FakeClinVarClient`, which holds ClinVar's submissions, statuses, and summary
reports in memory, so tests never reach ClinVar. Each of its calls can be told to fail.

### `management/__init__.py`

Empty file that marks `management` as a Python package.

### `management/commands/__init__.py`

Empty file that marks `commands` as a Python package.

### `management/commands/poll_clinvar.py`

The `poll_clinvar` command, which systemd runs next to Gunicorn. It runs a `Poller`
pass, sleeps `CSS_POLL_SLEEP_SECONDS`, and repeats. A failed pass is logged and doesn't
stop the loop. On SIGTERM it finishes the submission it's polling and exits. `--once`
runs one pass and exits. Run it locally with `just django-poll-clinvar`.

### `models.py`

Defines `Submission`, one request to ClinVar: the payload as the client sent it, the
ClinVar submission ID, its status, ClinVar's latest response, `updated` timestamp, error
code, and summary report, any error message, and when it was last and will next be
polled. It extends `common.models.SlugModel`, so its ID is a UUID and its slug is `S`
and the first 8 hex characters of the UUID, such as `S3f2a9c1e`. It keeps its change
history, and `get_absolute_url()` returns its page. `Submission.objects.due_to_poll()`
returns the submitted and processing submissions whose next poll time has passed, oldest
first. Also defines `ApiKey`, the key one client system sends to use the API. Only its
SHA-256 hash and a short prefix are stored, and each submission records the key that
sent it.

### `polling.py`

Polls ClinVar for submission statuses. `Poller.run_pass()` takes a batch of the
submissions that are due, oldest first, reads each one's status, and saves ClinVar's
response. A submission that reaches processed or error gets its summary report and stops
being polled. Otherwise, `next_delay()` doubles the wait from `CSS_POLL_MIN_DELAY` up to
`CSS_POLL_MAX_DELAY`, and waits at least as long as a 429's `Retry-After`. A failed
poll, including a failed report download, is logged and sent to Sentry, leaves the
status as it was, and doesn't stop the batch.

### `services.py`

Forwards a saved submission to ClinVar once with `forward_submission()`, which the API
and the staff Resend button share. If ClinVar accepts it, the submission is submitted,
with its ClinVar ID and a first poll time; if ClinVar rejects it, can't be reached, or
the CSS has no ClinVar key, it's send_failed, with the error. It never retries. Also
counts the records in a submission's content.

### `templates/clinvar_submission_service/detail.html`

A submission's page, in plain language: its status, who sent it, its ClinVar ID, when it
arrived and was last checked, what its status means, and each record's result and SCV
from the summary report. A send_failed submission's page has a Resend button. It never
shows raw JSON or ClinVar's error text; developers see those in the Django admin.

### `templates/clinvar_submission_service/list.html`

The CSS's home page: every submission, newest first, a page at a time, with a search by
ID or ClinVar ID.

### `templates/clinvar_submission_service/partials/header.html`

The top of every CSS page: the CSS's name and description from `core.tools`, and boxed
tabs for Submissions and, on a submission's page, that submission, with the current
page's tab active.

### `templates/clinvar_submission_service/partials/status.html`

A submission's status tag, in plain words and in the color key's colors: green when
ClinVar accepted it, red when it wasn't sent or has errors, and grey otherwise.

### `test_api.py`

Tests `forward_submission()` and each API endpoint against `FakeClinVarClient`: a
submission ClinVar accepts or rejects, a missing ClinVar key, that a failed send isn't
retried, bodies that aren't objects or hold too many records, 401s for missing, unknown,
and inactive keys, that a client can't read or list another client's submissions,
pagination, and the OpenAPI docs.

### `test_api_keys.py`

Tests that an API key is stored only as a hash, verifies only while active, and records
its last use; that `ApiKeyAuth` accepts and rejects the right headers; and that the
admin shows a new key once.

### `test_clients.py`

Tests each `ClinVarClient` call against a mocked requests session: the request's
envelope, headers, and timeout; parsing ClinVar's ID, status, update time, error code,
and report URL; which failures are retryable; that the API key never appears in logs or
errors; and `from_settings()`. Also tests `FakeClinVarClient`.

### `test_contract.py`

Checks `ClinVarClient` against ClinVar's real test endpoint with a dry run, which
creates nothing. It's skipped unless `RUN_CONTRACT_TESTS=1` and `CSS_CLINVAR_API_KEY`
are set in the environment.

### `test_polling.py`

Tests the poller against `FakeClinVarClient`: the backoff and its cap, each status
change, storing the summary report, retrying a failed report download, backing off on
errors and 429s, that one failing submission doesn't block the rest, that send_failed
and received submissions are never polled, batch size, and stopping mid-pass. Also tests
the command's `--once` and that SIGTERM stops its loop.

### `test_views.py`

Tests the staff pages: that each needs CSS permissions; the list's order, search,
pagination, and header; each status's tag color; the detail page's records and its
plain-language error; that only a send_failed submission has a Resend button; and that
resending sends it again, records who did, keeps a failed resend's new error, and
rejects other statuses and GET requests.

### `tests.py`

Tests the `Submission` slug, including a colliding one, its default status, and its
history; which submissions are due to poll; the admin pages; and that only users with
CSS permissions can open the home page, which the landing page links to.

### `urls.py`

Routes the CSS's pages under the `css` namespace: the submission list at the root, each
submission at `submissions/<slug>/`, its resend at `submissions/<slug>/resend/`, and the
API at `api/v1/` under `css:api-1`.

### `views.py`

Serves the CSS's pages to users with CSS permissions: the submission list, with search
and pagination, and each submission's page. The resend view, which takes only POSTs,
forwards a send_failed submission again through `services.forward_submission()` and
shows a plain error message if ClinVar still didn't get it.
