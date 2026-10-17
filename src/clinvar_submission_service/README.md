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

### `models.py`

Defines `Submission`, one request to ClinVar: the payload as the client sent it, the
ClinVar submission ID, its status, ClinVar's latest response, `updated` timestamp, error
code, and summary report, any error message, and when it was last and will next be
polled. It extends `common.models.SlugModel`, so its ID is a UUID and its slug is `S`
and the first 8 hex characters of the UUID, such as `S3f2a9c1e`. It keeps its change
history. `Submission.objects.due_to_poll()` returns the submitted and processing
submissions whose next poll time has passed. Also defines `ApiKey`, the key one client
system sends to use the API. Only its SHA-256 hash and a short prefix are stored, and
each submission records the key that sent it.

### `services.py`

Forwards a saved submission to ClinVar once with `forward_submission()`, which the API
and the staff Resend button share. If ClinVar accepts it, the submission is submitted,
with its ClinVar ID and a first poll time; if ClinVar rejects it, can't be reached, or
the CSS has no ClinVar key, it's send_failed, with the error. It never retries. Also
counts the records in a submission's content.

### `templates/clinvar_submission_service/index.html`

The CSS's home page, with its name and description from `core.tools`.

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

### `tests.py`

Tests the `Submission` slug, including a colliding one, its default status, and its
history; which submissions are due to poll; the admin pages; and that only users with
CSS permissions can open the home page, which the landing page links to.

### `urls.py`

Routes the CSS's pages under the `css` namespace: the home page, and the API at
`api/v1/` under `css:api-1`.

### `views.py`

Serves the CSS's pages to users with CSS permissions.
