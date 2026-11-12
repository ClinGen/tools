# `clinvar_submission_service`

This app is the ClinVar Submission Service (CSS), mounted at `/css/` with the URL
namespace `css`. It forwards ClinGen clients' batches to ClinVar and tracks each one
until ClinVar has processed it. Only users with `has_css_permissions` can use its pages.
"The ClinVar Submission Service" in `docs/design.md` describes how a batch moves through
the CSS.

### `__init__.py`

Empty file that marks `clinvar_submission_service` as a Python package.

### `admin.py`

Registers `Batch`, `Record`, `AffiliationSettings`, and `ApiKey` in the Django admin,
with their history. A
batch's ClinVar fields are read-only, since only ClinVar's responses should change them,
and its records are listed read-only, in order, with each one's result, on its page. A
record's page lists the batches it was sent in. Adding an API key generates its value
and shows it once, in a warning message; after that, only its prefix is shown.

### `api.py`

Serves the CSS's API, version 1, as a Django Ninja `NinjaAPI` at `/css/api/v1/`, with
OpenAPI docs at `/css/api/v1/docs`. Every endpoint needs an API key (see `api_auth.py`),
and a client sees only its own records. `POST /records` takes the client's affiliation
and one germline record (`content.RecordRequest`) and saves it to wait for a batch,
returning 201, or 200 if it replaced a waiting record with the same local ID. `GET
/records` lists the client's records a page at a time, `GET /records/{slug}` reads one
with its JSON, and `POST /records/{slug}/withdraw` withdraws a waiting one, or returns a
409 for any other. A record that doesn't match, or a body with submission-level fields,
gets a 422. Clients don't see batches, which staff make.

### `api_auth.py`

Defines `ApiKeyAuth`, the Ninja auth class for the CSS's API. It reads the key from the
`X-API-Key` header and accepts it only if it's an active `ApiKey`, which becomes
`request.auth`.

### `apps.py`

Configures the `clinvar_submission_service` app.

### `clients.py`

Wraps the NCBI ClinVar Submission API in `ClinVarClient`, built on requests, with one
method for each call the CSS makes: create a batch (or a dry run), read its status, and
download its summary report. Every request sends the `SP-API-KEY` header and a timeout.
A failed request raises `ClinVarError`, which says whether it's worth retrying
(timeouts, 429s, and 5xx are; 400s and 401s aren't) and carries a 429's `Retry-After`.
Nothing it logs or raises includes the API key. `ClinVarClient.from_settings()` builds
one from the `CSS_` settings and raises `ImproperlyConfigured` without a key, or returns
a `simulation.SimulatedClinVarClient` when `CSS_SIMULATE_CLINVAR` is on.

### `content.py`

Describes the ClinVar content the API accepts as Ninja schemas, with ClinVar's field
names as aliases: `Content` holds 1 to 10,000 germline records, each with one HGVS
variant, one condition, and one observation, plus the assertion criteria, on-behalf-of
organization, and release status. `RecordRequest`, the API's body, wraps one
`GermlineRecord` with the client's `Affiliation`: its AS ID and name. A field the CSS
doesn't model is rejected, and an update must name its SCV. `fields_of()` and
`record_fields()` copy one record, or each of the content's records, into `Record`
fields.

### `fakes.py`

Defines `FakeClinVarClient`, which holds ClinVar's submissions, statuses, and summary
reports in memory, so tests never reach ClinVar. Each of its calls can be told to fail.
Also builds sample content: `make_record()` returns a germline record, with any field
replaced, and `make_content()` wraps records in content.

### `fixtures/test_batches.json`

A Django fixture with a VCI API key, records from five made-up affiliations, and eight
batches of them, with at least one batch in each status: ones ClinVar never got (not
sent and send failed), and submitted, processing, processed, and error ones sent to
ClinVar, with made-up ClinVar IDs, responses, and summary reports with SCVs and errors.
Each attempt's result matches its batch's report. Records are in every status, including
waiting ones not yet in a batch, a withdrawn one, accepted ones with their SCVs, one
that failed and waits again, and one retried across two batches. Two affiliations have
settings. No batch is made by a client, and none is due to poll. Load it with `just
django-loaddata-test`; tests load it with `fixtures = ["test_batches.json"]`.

### `forms.py`

Defines `AffiliationSettingsForm`, which edits an affiliation's `AffiliationSettings`.
It rejects values that aren't one of ClinVar's choices, or an on-behalf-of ID below 1,
with plain messages, and requires both the assertion criteria's database and ID, or
neither.

### `management/__init__.py`

Empty file that marks `management` as a Python package.

### `management/commands/__init__.py`

Empty file that marks `commands` as a Python package.

### `management/commands/load_css_sample_data.py`

Defines the `load_css_sample_data` command, which `just django-loaddata-test` runs. In
one transaction, it deletes the CSS's batches, records, attempts, and affiliation
settings, then loads `fixtures/test_batches.json`, so loading again resets the sample
data instead of conflicting with rows already there. It keeps API keys.

### `management/commands/poll_clinvar.py`

The `poll_clinvar` command, which systemd runs next to Gunicorn. It runs a `Poller`
pass, sleeps `CSS_POLL_SLEEP_SECONDS`, and repeats. A failed pass is logged and doesn't
stop the loop. On SIGTERM it finishes the batch it's polling and exits. `--once` runs
one pass and exits. Run it locally with `just django-poll-clinvar`.

### `models.py`

Defines `Batch`, one request to ClinVar: its affiliation (its AS ID and name), the staff
member who made it, its records, through `BatchRecord`, the ClinVar submission ID, its
status (named relative to ClinVar, such as `submitted_to_clinvar`, and labeled in
ClinVar's words, with `status_help` saying what it means), ClinVar's latest response,
`updated` timestamp, error code, and summary report, any error message, and when it was
last and will next be polled, plus the content's assertion criteria, the organization
it's on behalf of, and its release status. It extends `common.models.SlugModel`, so its
ID is a UUID and its slug is `B` and the first 8 hex characters of the UUID, such as
`B3f2a9c1e`. It keeps its change history, and `get_absolute_url()` returns its page.
`Batch.objects.due_to_poll()` returns the submitted and processing batches whose next
poll time has passed, oldest first. Also defines `Record`, one germline variant
classification a client sent, with slug `R` and the start of its UUID, its own ClinVar
JSON, affiliation, client, its page from `get_absolute_url()`, a status relative to the
CSS's batches and ClinVar with `status_help` for its tooltip, and a copy of its fields:
the variant's HGVS and assembly, the condition, the classification, mode of inheritance,
date last evaluated, comment, how the evidence was gathered, and the record's SCV for an
update. Its choices, defined above the models, are ClinVar's terms, so a value is
exactly what ClinVar expects; the classifications are the five ACMG terms the VCI uses.
Also defines `BatchRecord`, one attempt to send a record in a batch: its position in the
batch's `germlineSubmission` and ClinVar's result for it (Success or Error, the SCV, and
ClinVar's errors for developers). A record is in a batch at most once, and can be in
several batches over time. Also defines `AffiliationSettings`, the submission-level
values staff set once per affiliation, with history: its assertion criteria, the
organization its batches are on behalf of, and its release status. Also defines
`ApiKey`, the key one client system sends to use the API. Only its SHA-256 hash and a
short prefix are stored, and each record notes the key that sent it.

### `polling.py`

Polls ClinVar for batch statuses. `Poller.run_pass()` takes a batch of the batches that
are due, oldest first, reads each one's status, and saves ClinVar's response. A batch
that reaches processed or error gets its summary report, which
`services.save_results()` copies onto its records, and stops being polled.
Otherwise, `next_delay()` doubles the wait from `CSS_POLL_MIN_DELAY` up to
`CSS_POLL_MAX_DELAY`, and waits at least as long as a 429's `Retry-After`. A failed
poll, including a failed report download, is logged and sent to Sentry, leaves the
status as it was, and doesn't stop the pass.

### `services.py`

Saves a record a client sent with `save_record()`, which replaces the affiliation's
waiting record with the same local ID, if there is one, so its history keeps the old
version. `withdraw_record()` withdraws a waiting record and notes who did in its
history, or raises `NotWithdrawableError` for any other. `check_batchable()` checks that
records can make a batch, and `make_batch()` makes a not-yet-sent batch of one
affiliation's waiting records, in the order given, copies the affiliation's
`AffiliationSettings` onto it, and marks the records as in a batch; it raises
`BatchNotMadeError`, with a message for staff, for no records, more than 10,000, mixed
affiliations, or records that aren't waiting. `build_payload()` builds a batch's ClinVar
content from its records' JSON, in order, and the batch's submission-level fields.
`report_results()` reads each record's result from a summary report by local ID, and
`save_results()` saves them: a record ClinVar accepted gets its SCV, and one that failed
goes back to waiting, with ClinVar's errors kept on its attempt. Forwards a batch to
ClinVar once with `forward_batch()`, which sends that built content and which the staff
Resend button uses. If ClinVar accepts it, the batch is submitted, with its ClinVar ID
and a first poll `CSS_FIRST_POLL_DELAY` out; if ClinVar rejects it, can't be reached, or
the CSS has no ClinVar key, it's send_to_clinvar_failed, with the error, and its records
stay in it. It never retries.

### `templatetags/__init__.py`

Marks `templatetags` as a package, so Django finds the CSS's template tags.

### `templatetags/css_tags.py`

Defines the `simulating_clinvar` tag, which says whether `CSS_SIMULATE_CLINVAR` is on,
so `partials/header.html` can show its banner without each view passing the setting.

### `templates/clinvar_submission_service/affiliation_settings.html`

The form where staff set an affiliation's ClinVar settings, in the Affiliations section,
with each field's help text and any error in plain words.

### `templates/clinvar_submission_service/affiliations.html`

The Affiliations page: each affiliation that has records or batches, by name, with a
column for each of the Records list's pills (All, then each record status) and each of
the Batches list's pills (All, then each batch status). Each count links to that list
filtered to the affiliation and status. A gear icon, with a title and screen-reader text
naming the affiliation, links to its settings.

### `templates/clinvar_submission_service/detail.html`

A batch's page, in plain language: its status, affiliation, who sent it, its ClinVar ID,
when it arrived and was last checked, and what its status means. Its records table shows
each record's variant, condition, classification, inheritance, date last evaluated, and
whether it's new or an update, with its result and SCV once ClinVar has reported. A
send_to_clinvar_failed batch's page has a Resend button. It never shows raw JSON or
ClinVar's error text; developers see those in the Django admin.

### `templates/clinvar_submission_service/record.html`

A record's page: its fields and status, a Withdraw button while it waits, each batch it
was in with that batch's status, ClinVar's result for the record, and its SCV, and its
history in plain words. Like the batch page, it never shows raw JSON or ClinVar's
errors.

### `templates/clinvar_submission_service/records.html`

The Records page, laid out like the batch list, with the filters from
`partials/list_filters.html` searching genes, HGVS, local IDs, and affiliations.

### `templates/clinvar_submission_service/new_batch.html`

The page where staff make a batch for one affiliation: its waiting records with
checkboxes, an Add Every Waiting Record shortcut, a review of the picked records, and a
Send to ClinVar button.

### `templates/clinvar_submission_service/partials/list_filters.html`

The filters above the Records and Batches lists: a notice for an unknown affiliation ID,
an affiliation select that reloads the list when changed, a New Batch button when the
list shows one affiliation with waiting records, the status pills, and a search box that
updates the results as you type, sending the other filters along.

### `templates/clinvar_submission_service/partials/record_results.html`

The Records page's results: the record count and the table, or a message when there are
none. It's the whole response to an HTMX request.

### `templates/clinvar_submission_service/partials/record_status.html`

A record's status tag, colored by status, with what it means in a tooltip. With `href`,
the tag links to the list filtered to that status.

### `templates/clinvar_submission_service/list.html`

The CSS's batch list: the filters from `partials/list_filters.html`, whose search, as in
the HCI, is a search box that updates the results as you type, sending the active
filters along. Pills show all batches or only those in one status, and the search
matches IDs, affiliations, genes, and HGVS.

### `templates/clinvar_submission_service/partials/results.html`

The list's results: how many batches match and the `BatchTable`, or a line saying none
do. The list page includes it, and the search box and the table's sort and page links
fetch it alone with HTMX and swap it in.

### `templates/clinvar_submission_service/partials/breadcrumb_trail.html`

The breadcrumbs nav that `partials/breadcrumbs.html` fills in: a section crumb, linked
when there's a page below it, and the current page, in bold and marked current.

### `templates/clinvar_submission_service/partials/breadcrumbs.html`

A page's breadcrumbs, as in the HCI. It starts at the page's section (Affiliations,
Records, or Batches) and, below a section's list, ends with the current page, such as
Records / R3f2a9c1e Details or Records / New Batch.

### `templates/clinvar_submission_service/partials/header.html`

The top of every CSS page: a banner saying ClinVar is simulated while
`CSS_SIMULATE_CLINVAR` is on, the CSS's name and description from `core.tools`, then a
navbar linking to the Records, Batches, and Affiliations sections, with the current
section in bold.

### `templates/clinvar_submission_service/partials/status.html`

A batch's status tag, in ClinVar's words (the status's label), with `Batch.status_help`
in a tooltip on the tag, from `common/tooltip.html`. Given an `href`, as in the batches
table, the tag is a link. Its color follows the color key: green when processed, red
when the send failed or ClinVar reported an error, and grey otherwise.

### `templates/clinvar_submission_service/partials/record_result.html`

A record's result on a batch's page, with a tooltip on the tag: Not Sent when ClinVar
doesn't have the batch, No Result Yet before ClinVar reports, and then ClinVar's own
words from the summary report, Success or Error.

### `simulation.py`

Defines `SimulatedClinVarClient`, which has `ClinVarClient`'s methods and answers as
ClinVar might when `CSS_SIMULATE_CLINVAR` is on, so the workflow can be tried without
ClinVar. Sending a batch returns a new `SUB` ID, or fails about one time in ten so
Resend can be tried. The web server and the poller are separate processes, so it keeps
nothing in memory and reads each batch and its records from the database. Each poll
moves a batch one step: submitted, then processing, then processed or error, with
ClinVar's error code. Its summary report, in ClinVar's shape, gives each record Success
with an SCV or Error with a plausible message, about 85% Success, decided by a hash of
the ClinVar ID and local ID so it's the same on every call.

### `tables.py`

`BatchTable`, the django-tables2 table on the list page: each batch's ID, linked to its
page, its affiliation, linked to the list of that affiliation's batches, its records'
genes, the staff member who made it, its status tag, linked to the list filtered to that
status (keeping the affiliation filter), its ClinVar ID, and when the CSS received it.
It sorts by every column but the genes and status. `RecordTable`, on the Records page,
shows each record's ID, linked to its page, local ID, affiliation, linked to the list of
its records, gene and HGVS, classification, status tag, linked to the list filtered to
that status (keeping the affiliation filter), and when the CSS received it.

### `test_api.py`

Tests each API endpoint: that a posted record waits with its JSON, fields, affiliation,
and client, that re-posting a waiting record with the same local ID replaces it and
keeps history, and that a batched record, another affiliation's, or one without a local
ID makes a new record; that a bad record, a missing or bad affiliation, a
submission-level field, or a body over the upload limit is rejected and saves nothing;
that a client can withdraw a waiting record, with who did in its history, and gets a 409
for any other; 401s for missing, unknown, and inactive keys; that a client can't read,
list, or withdraw another client's records; pagination; the OpenAPI docs and endpoints;
and that the old batch endpoints are gone.

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

Tests the fixture: it has a batch and a record in every status, from several
affiliations, only sent batches have a ClinVar ID, only finished ones have a summary
report, each batch's records match what parsing its content gives, each attempt's result
matches its batch's report, a record is retried across two batches, and every CSS page
renders, including each batch's, record's, new batch, and settings page. Also tests that
`load_css_sample_data` can run twice, replaces attempts numbered differently from the
fixture and data made in the UI, and keeps API keys.

### `test_polling.py`

Tests the poller against `FakeClinVarClient`: the backoff and its cap, that it maps each
of ClinVar's statuses onto ours, each status change, storing the summary report,
retrying a failed report download, backing off on errors and 429s, that one failing
batch doesn't block the rest, that batches not sent to ClinVar, or whose send failed,
are never polled, polls per pass, and stopping mid-pass. Also tests that a processed
batch accepts each record with its SCV, that a partly failed one returns its failures to
waiting with ClinVar's errors kept, and that a result for an unknown local ID is logged
and skipped. Also tests the command's `--once` and that SIGTERM stops its loop.

### `test_services.py`

Tests `make_batch()` and `forward_batch()` against `FakeClinVarClient`: that a batch is
made from one affiliation's waiting records, in order, marks them as in a batch, and
copies its affiliation's settings or, without any, leaves them out; that no records,
mixed affiliations, withdrawn or batched records, and too many records are refused and
save nothing; that a batch ClinVar accepts is submitted with its records' content; and
that a rejected send, or a missing ClinVar key, leaves it send_to_clinvar_failed with
its records in it, isn't retried, and can be resent.

### `test_simulation.py`

Tests the simulated ClinVar: that `from_settings()` returns it only when the flag is on
and that the flag is off by default; that sending returns new IDs, sometimes fails, and
returns nothing for a dry run; that each poll moves a batch one step, with the right
error code for some or all records failing; that the report has a result per record in
ClinVar's shape and is the same on every call; and that the poller and `save_results()`
work against it end to end. Also tests that a sent batch's first poll waits
`CSS_FIRST_POLL_DELAY`, that every CSS page shows the simulation banner only while the
flag is on, and that the dev settings shorten the poll delays only while simulating.

### `test_views.py`

Tests the staff pages: that each needs CSS permissions; the list's order, affiliations
and variants, status filter and its pills, affiliation filter (alone, with the status
filter, and with an unknown ID), search by ID, affiliation, gene, or HGVS, sorting,
pagination that keeps the search and filters, the results-only response to HTMX, and
header; each status's tag color, ClinVar's wording, and tooltip, on the list and the
detail page, the list's tags linking to their status (and the detail page's not), and an
Error's tooltip by error code; that no page uses the old wording; the detail page's
records, with ClinVar's result matched by local ID, an update's SCV, and records ClinVar
never got or hasn't reported on; its plain-language error; that only a
send_to_clinvar_failed batch has a Resend button; that resending sends it again, records
who did, keeps a failed resend's new error, and rejects other statuses and GET requests;
and that staff can withdraw a waiting record, with who did in its history, but not a
batched or accepted one, and only with a POST; that the affiliation settings page shows,
saves, and updates an affiliation's settings, records who saved them, names an
affiliation known only from its records, rejects bad values with plain messages, 404s
for an unknown affiliation, and is linked from the affiliations page; and the Records
page's order, status pills and filter, affiliation filter, search by gene, HGVS, local
ID, or affiliation, status tags linking to their filter, results-only HTMX response, and
that it shows no raw JSON; and that the new batch page lists an affiliation's waiting
records, reviews the picked records or every waiting one, makes and sends the batch and
records who did, refuses an empty, mixed, or not-waiting selection with a plain message,
404s for an unknown affiliation, and is linked from the Records page for one
affiliation; and that a record's page shows its fields, status, attempts with their
batch, result, and SCV, and its history in plain words, offers Withdraw only while the
record waits, is linked from the Records list and batch pages, shows no raw JSON or
ClinVar errors, and 404s for an unknown slug. Against the fixtures, tests the
affiliations page's counts for each pill, an affiliation known only from its records,
order, columns matching each list's pills, links to the filtered lists, and labeled
settings gear; and, on both lists, the affiliation select's options, order, and
selection, that it keeps the status and search, and that New Batch shows only for one
affiliation with waiting records. Also tests each page's breadcrumbs, that the navbar
under the subtitle links to each section in order and bolds the current one, and that no
page has the old tabs.

### `tests.py`

Tests the `Batch` slug, including a colliding one, its default status, and its history;
a `Record`'s order, history, and classifications, and that it's deleted with its batch;
which batches are due to poll; the admin pages, including a batch's records; and that
only users with CSS permissions can open the home page, which the landing page links to.
Also tests `BatchRecord`: a record's order in a batch, that it's in a batch once but can
be tried in several, that deleting a batch keeps its records, and `build_payload()`.
Also tests a standalone `Record`: its R slug, default status, history, status help, and
bulk slugs that avoid taken ones. Also tests that the migration naming each status
relative to ClinVar renames old rows and their history, and back. Also tests that
`AffiliationSettings` keeps history and that an affiliation has one.

### `urls.py`

Routes the CSS's pages under the `css` namespace. The root redirects to the records
list at `records/`, since staff mostly work from records. Each record is at
`records/<slug>/` and its withdraw at `records/<slug>/withdraw/`. The batch list is at
`batches/`, each batch at `batches/<slug>/`, and its resend at
`batches/<slug>/resend/`. The affiliations page is at `affiliations/` and an
affiliation's new batch at `affiliations/<id>/new-batch/`. The API is at `api/v1/`
under `css:api-1`.

### `views.py`

Serves the CSS's pages to users with CSS permissions: the batch list, with its status
and affiliation filters, search, sorting, and pagination, and just its results for an
HTMX request; the Records page, with the same kinds of filters and search; on both
lists, an affiliation select of every known affiliation, named from its newest record or
batch, and a New Batch button for one affiliation with waiting records; the affiliations
page, which counts each affiliation's records and batches like each list's pills, with
links to the filtered lists; each affiliation's settings page, which shows and saves its
`AffiliationSettings`; the new batch page, which lists an affiliation's waiting records,
reviews the picked ones, and makes and sends the batch through `services.make_batch()`
and `forward_batch()`, with a plain message when it can't; and each batch's page, which
pairs each `Record` with its result in ClinVar's summary report. The resend view, which
takes only POSTs, forwards a send_to_clinvar_failed batch again through
`services.forward_batch()` and shows a plain error message if ClinVar still didn't get
it. The withdraw view, also POST-only, withdraws a waiting record through
`services.withdraw_record()` and returns to the batch list with a plain message.
