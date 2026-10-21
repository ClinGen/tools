# `clinvar_submission_service`

This app is the ClinVar Submission Service (CSS), mounted at `/css/` with the URL
namespace `css`. It forwards ClinGen clients' submissions to ClinVar and tracks each one
until ClinVar has processed it. Only users with `has_css_permissions` can use its pages.
"The ClinVar Submission Service" in `docs/design.md` describes how a submission moves
through the CSS.

### `__init__.py`

Empty file that marks `clinvar_submission_service` as a Python package.

### `admin.py`

Registers `Submission`, `Record`, and `ApiKey` in the Django admin, with their history.
A submission's ClinVar fields are read-only, since only ClinVar's responses should
change them, and its records are listed read-only on its page. Adding an API key
generates its value and shows it once, in a warning message; after that, only its prefix
is shown.

### `api.py`

Serves the CSS's API, version 1, as a Django Ninja `NinjaAPI` at `/css/api/v1/`, with
OpenAPI docs at `/css/api/v1/docs`. Every endpoint needs an API key (see `api_auth.py`),
and a client sees only its own submissions. `POST /submissions` takes the client's
affiliation and the ClinVar content (`content.SubmissionRequest`), saves them as a
submission with its records, and forwards the content as sent, `GET /submissions` lists
the client's submissions a page at a time, and `GET /submissions/{slug}` reads one with
ClinVar's responses. Content that doesn't match, including more than 10,000 records,
gets a 422.

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

### `content.py`

Describes the ClinVar content the API accepts as Ninja schemas, with ClinVar's field
names as aliases: `Content` holds 1 to 10,000 germline records, each with one HGVS
variant, one condition, and one observation, plus the assertion criteria, on-behalf-of
organization, and release status. `SubmissionRequest`, the API's body, wraps the content
with the client's `Affiliation`: its AS ID and name. A field the CSS doesn't model is
rejected, and an update must name its SCV. `submission_fields()` and `record_fields()`
copy validated content into `Submission` and `Record` fields.

### `fakes.py`

Defines `FakeClinVarClient`, which holds ClinVar's submissions, statuses, and summary
reports in memory, so tests never reach ClinVar. Each of its calls can be told to fail.
Also builds sample content: `make_record()` returns a germline record, with any field
replaced, and `make_content()` wraps records in content.

### `fixtures/test_submissions.json`

A Django fixture with a VCI API key and eight submissions from five made-up
affiliations, with at least one in each status and one to three records each: received
and send_failed ones ClinVar never got, and submitted, processing, processed, and error
ones forwarded to ClinVar, with made-up ClinVar IDs, responses, and summary reports with
SCVs and an error. None is due to poll. Load it with `just django-loaddata-test`; tests
load it with `fixtures = ["test_submissions.json"]`.

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

Defines `Submission`, one request to ClinVar: the affiliation the client sent it for
(its AS ID and name), the ClinVar content as the client sent it, the ClinVar submission
ID, its status, ClinVar's latest response, `updated` timestamp, error code, and summary
report, any error message, and when it was last and will next be polled, plus the
content's assertion criteria, the organization it's on behalf of, and its release
status. It extends `common.models.SlugModel`, so its ID is a UUID and its slug is `S`
and the first 8 hex characters of the UUID, such as `S3f2a9c1e`. It keeps its change
history, and `get_absolute_url()` returns its page. `Submission.objects.due_to_poll()`
returns the submitted and processing submissions whose next poll time has passed, oldest
first. Also defines `Record`, one germline variant classification in a submission and a
copy of one item in its payload's `germlineSubmission`: the variant's HGVS and assembly,
the condition, the classification, mode of inheritance, date last evaluated, comment,
how the evidence was gathered, and the record's SCV for an update. Its choices, defined
above the models, are ClinVar's terms, so a value is exactly what ClinVar expects; the
classifications are the five ACMG terms the VCI uses. Also defines `ApiKey`, the key one
client system sends to use the API. Only its SHA-256 hash and a short prefix are stored,
and each submission records the key that sent it.

### `polling.py`

Polls ClinVar for submission statuses. `Poller.run_pass()` takes a batch of the
submissions that are due, oldest first, reads each one's status, and saves ClinVar's
response. A submission that reaches processed or error gets its summary report and stops
being polled. Otherwise, `next_delay()` doubles the wait from `CSS_POLL_MIN_DELAY` up to
`CSS_POLL_MAX_DELAY`, and waits at least as long as a 429's `Retry-After`. A failed
poll, including a failed report download, is logged and sent to Sentry, leaves the
status as it was, and doesn't stop the batch.

### `services.py`

Saves a received submission and a `Record` for each of its records, in one transaction,
with `save_submission()`. Forwards a saved submission to ClinVar once with
`forward_submission()`, which the API and the staff Resend button share. If ClinVar
accepts it, the submission is submitted, with its ClinVar ID and a first poll time; if
ClinVar rejects it, can't be reached, or the CSS has no ClinVar key, it's send_failed,
with the error. It never retries.

### `templates/clinvar_submission_service/affiliations.html`

The Affiliations tab: each affiliation that has submissions, by name, with how many of
its submissions ClinVar never got, ClinVar is checking, ClinVar accepted, and have
errors. Each name links to the list filtered to that affiliation.

### `templates/clinvar_submission_service/detail.html`

A submission's page, in plain language: its status, affiliation, who sent it, its
ClinVar ID, when it arrived and was last checked, and what its status means. Its records
table shows each record's variant, condition, classification, inheritance, date last
evaluated, and whether it's new or an update, with ClinVar's result and SCV once ClinVar
has reported. A send_failed submission's page has a Resend button. It never shows raw
JSON or ClinVar's error text; developers see those in the Django admin.

### `templates/clinvar_submission_service/list.html`

The CSS's home page: every submission, newest first, a page at a time, with its
affiliation and its records' genes. Toggles show all submissions, only the ones ClinVar
never got, or only the ones sent to ClinVar, a link on an affiliation's name shows only
its submissions, and a search matches IDs, affiliations, genes, and HGVS.

### `templates/clinvar_submission_service/partials/header.html`

The top of every CSS page: the CSS's name and description from `core.tools`, and boxed
tabs for Submissions, that submission when you're on a submission's page, and
Affiliations, with the current page's tab active.

### `templates/clinvar_submission_service/partials/status.html`

A submission's status tag, in plain words and in the color key's colors: green when
ClinVar accepted it, red when it wasn't sent or has errors, and grey otherwise.

### `test_api.py`

Tests `forward_submission()` and each API endpoint against `FakeClinVarClient`: a
submission ClinVar accepts or rejects, a missing ClinVar key, that a failed send isn't
retried, that a body's affiliation, fields, and records are saved and only its content
is forwarded, as sent, that a missing or bad affiliation gets a 422, that bodies that
aren't objects, hold too many records, or don't match `Content` get a 422 and save
nothing, 401s for missing, unknown, and inactive keys, that a client can't read or list
another client's submissions, pagination, and the OpenAPI docs and their fields.

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

### `test_fixtures.py`

Tests the fixture: it has a submission in every status, from several affiliations, only
forwarded ones have a ClinVar ID, only finished ones have a summary report, each
submission's records match what parsing its payload gives, and every submission's page
renders.

### `test_polling.py`

Tests the poller against `FakeClinVarClient`: the backoff and its cap, each status
change, storing the summary report, retrying a failed report download, backing off on
errors and 429s, that one failing submission doesn't block the rest, that send_failed
and received submissions are never polled, batch size, and stopping mid-pass. Also tests
the command's `--once` and that SIGTERM stops its loop.

### `test_views.py`

Tests the staff pages: that each needs CSS permissions; the list's order, affiliations
and variants, sent filter, affiliation filter (alone, with the sent filter, and with an
unknown ID), search by ID, affiliation, gene, or HGVS, pagination, and header; each
status's tag color; the detail page's records, with ClinVar's result matched by local
ID, an update's SCV, and records ClinVar never got or hasn't reported on; its
plain-language error; that only a send_failed submission has a Resend button; and that
resending sends it again, records who did, keeps a failed resend's new error, and
rejects other statuses and GET requests. Against the fixtures, tests the affiliations
page's counts, order, links, and tab.

### `tests.py`

Tests the `Submission` slug, including a colliding one, its default status, and its
history; a `Record`'s order, history, and classifications, and that it's deleted with
its submission; which submissions are due to poll; the admin pages, including a
submission's records; and that only users with CSS permissions can open the home page,
which the landing page links to.

### `urls.py`

Routes the CSS's pages under the `css` namespace: the submission list at the root, the
affiliations page at `affiliations/`, each submission at `submissions/<slug>/`, its
resend at `submissions/<slug>/resend/`, and the API at `api/v1/` under `css:api-1`.

### `views.py`

Serves the CSS's pages to users with CSS permissions: the submission list, with its sent
and affiliation filters, search, and pagination; the affiliations page, which counts
each affiliation's submissions by status and names it from its newest submission; and
each submission's page, which pairs each `Record` with its result in ClinVar's summary
report. The resend view, which takes only POSTs, forwards a send_failed submission again
through `services.forward_submission()` and shows a plain error message if ClinVar still
didn't get it.
