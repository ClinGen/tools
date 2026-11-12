# ClinGen Tools Design Doc

## Context and Scope

ClinGen Tools is a web application built by the Stanford University ClinGen team. It
houses the team's internal tools in one Django project, served from
tools.clinicalgenome.org:

- **Affiliations Service (AS)**, at `/as/`: replaces `affiliations-service`, but is
  built here from scratch rather than ported.
- **ClinVar Submission Service (CSS)**, at `/css/`: replaces
  `clinvar-submission-service`.
- **Email Transfer Service (ETS)**, at `/ets/`: new; it replaces nothing.

The landing page at `/` links to each tool.

Before this project, each tool was its own Django application with its own repository,
server, and deployment. The AS and the CSS share the same stack, the same dependencies,
and most of the same supporting code (authentication, shared views, templates, and
infrastructure), all adapted from the HLA Curation Interface (HCI). Keeping them apart
meant making every dependency upgrade, security fix, and infrastructure change once per
tool.

This document is for engineers who are new to the codebase and for product owners who
want to understand the system's architecture and key design decisions. It covers what
the tools share, how they're kept apart, and the design of the AS, the CSS, and the ETS.

## Goals

- Run every internal tool from one codebase, one set of dependencies, one server, and
  one deployment.
- Give each tool a stable URL prefix, so a tool's links and API base URL don't depend on
  which other tools exist.
- Keep each tool's code separate enough that a change to one tool can't break another
  without also changing shared code.
- Let ClinGen staff find every tool from one landing page.
- Run reliably on minimal infrastructure, using the same setup as the HCI.

## Non-Goals

- ClinGen Tools is not a home for public, curator-facing applications like the HCI.
  Those have their own users, uptime needs, and release schedules.
- The tools don't share domain data. Each tool owns its models; a shared app holds only
  supporting code such as authentication and common views.
- We don't keep the standalone AS deployment running once the AS has moved here. The
  standalone CSS was never deployed to production.

## Design

### System Context

ClinGen Tools is a single Django application on a single server. Caddy terminates TLS
for tools.clinicalgenome.org and proxies every request to Gunicorn, and Django routes
each request to a tool by its path prefix. Caddy knows about one tool path: it lets the
CSS's submissions endpoint take bodies up to 64 MB, since a submission can hold 10,000
records, and keeps every other path at Django's 2.5 MB default.

Each tool keeps the external integrations it had as a standalone service:

- **AS**: other ClinGen tools (the GCI, the VCI, and others) read and write
  affiliations, the users in them, and their memberships through its REST API.
  Affiliations, CDWGs, and users can carry the UUID that the Group and Personnel
  Management (GPM) system at UNC gives them.
- **CSS**: ClinGen clients send records through its API, and staff send them in batches
  to the NCBI ClinVar Submission API.
- **ETS**: reads and changes user accounts in the Gene Curation Interface (GCI) and the
  Variant Curation Interface (VCI). Those accounts live in two places: an AWS Cognito
  user pool, which handles sign-in, and the `GeneVariantCuration` DynamoDB table, which
  holds each user's record. The ETS calls both through boto3.

### Application Architecture

ClinGen Tools is a standard Django monolith, like the HCI. Server-rendered templates are
the UI, with HTMX where a page needs a little interactivity.

**Key libraries:**

- **Web framework**: Django
- **WSGI server**: Gunicorn
- **Database**: SQLite
- **Static files**: WhiteNoise (compressed, fingerprinted)
- **Backups**: django-dbbackup, to S3
- **Audit history**: django-simple-history
- **Error monitoring**: Sentry
- **Frontend CSS**: Bulma
- **Partial page updates**: HTMX
- **Tooltips**: Tippy.js (with Popper)
- **Tables**: django-tables2
- **Authentication**: Clerk + custom `ClerkBackend`
- **API framework**: Django Ninja
- **AWS client (ETS)**: boto3
- **HTTP client (CSS)**: requests

Every tool's API uses Django Ninja. The AS's API is new; it doesn't keep the standalone
AS's URLs or response formats.

### URL Layout

`src/config/urls.py` mounts each tool's URLconf under its prefix, with a namespace
matching the prefix:

- `/`: the landing page (`core`).
- `/as/`: the AS UI. Its API lives under `/as/api/v1/`.
- `/css/`: the CSS UI. Its API lives under `/css/api/v1/`.
- `/ets/`: the ETS.
- `/admin/`: the Django admin, shared by every tool.

Because every tool lives under a prefix, templates and views must build URLs with
`{% url %}` and `reverse()` and never hard-code paths.

### Project Layout

The layout follows the HCI. Python code lives in `src/`, and tooling lives at the root.
`as` is a Python keyword, and `css` is easy to confuse with stylesheets, so Django apps
are named for what they hold rather than for a tool's abbreviation.

Shared apps:

- `src/config/`: URL routing, WSGI entry point, and layered settings (`base`, `dev`,
  `test`, `prod`).
- `src/auth_/`: authentication, `UserProfile`, and permission mixins.
- `src/common/`: shared views, tables, history diffing, template partials, and test
  mixins.
- `src/core/`: the landing page and other pages that belong to no tool.
- `src/templates/` and `src/static/`: the base layout, error pages, and vendored assets.

Tool apps:

- `src/affiliations_service/`: the AS.
- `src/clinvar_submission_service/`: the CSS, including its `poll_clinvar` command.
- `src/email_transfer_service/`: the ETS.

A tool may grow more than one app; prefix the extra apps' names so they sort with the
tool's main app. A tool app may import from shared apps but never from another tool's
app. If two tools need the same code, move it into a shared app.

### Data Model

All tools share one SQLite database. Each tool's tables are prefixed with its app label,
so they can't collide. No tool has a foreign key to another tool's models. If that ever
seems necessary, the data probably belongs in a shared app, and that's a design decision
worth recording here first.

Every model carries full change history via `django-simple-history`.

Every model also has a random UUID primary key instead of an auto-incrementing integer,
from `common.models.UUIDModel`. UUIDs let data from the standalone AS and CSS move into
the shared database without ID clashes, and they don't reveal how many records exist.
History rows use UUIDs too. Django's own models, such as `User`, keep their integer IDs.

A model that staff refer to by ID extends `common.models.SlugModel`, which adds a
human-readable slug: a prefix letter for the model and the first 8 hex characters of the
UUID, like a short Git hash. For example, an email transfer's slug looks like
`T3f2a9c1e`. If a new object's slug is already taken, it gets a new UUID. This replaces
the HCI's zero-padded integer slugs, such as `T000001`.

### Authentication and Authorization

Staff sign in once and can then use every tool they've been granted. Permissions are per
tool: being able to manage affiliations doesn't mean being able to resend ClinVar
submissions. Each tool's views check its own permission through the mixins in `auth_`.

Staff sign in with Clerk, the identity provider every ClinGen app is moving to. `auth_`
follows the CSS: sign-in uses Clerk's embedded widget, and a custom `ClerkBackend`
verifies the Clerk session on each request. The Django admin keeps Django's own staff
logins.

Machine clients use API keys, as they did with the standalone services. A key belongs to
one tool: an AS key can't call the CSS API. Keys are hashed at rest, and staff manage
them in the Django admin.

### The Affiliations Service

The AS is the source of truth for users and groups inside and outside of ClinGen apps:
the users in ClinGen's affiliations and the affiliations themselves. It replaces the
standalone `affiliations-service`, but it isn't a port: it starts with an empty
database, its own data model, and a new API. It doesn't keep the old service's URLs,
response formats, legacy JSON format, or API keys. Moving the old service's clients and
data to the AS is later work.

**Affiliations.** An affiliation is a group that curates for ClinGen: a Variant Curation
Expert Panel (VCEP), a Gene Curation Expert Panel (GCEP), a Somatic Cancer VCEP
(SC-VCEP), or an independent curation group. Its status is one of applying (the
default), active, inactive, retired, or archived. Each affiliation belongs to a Clinical
Domain Working Group (CDWG), such as Cardiovascular or Hereditary Cancer. CDWG names are
unique, ignoring case. An affiliation also has a full name, a short name, and a list of
ClinVar submitter IDs.

**IDs.** Affiliations keep the old ID scheme, because GCI and VCI curation records
already use these IDs. Outside the AS, an affiliation's affiliation ID and expert panel
ID are its canonical IDs. Inside, every record also has a UUID primary key, the AS ID,
which the API calls `id`; we never call it an affiliation ID.

- Each new affiliation gets the next affiliation ID, counting up from 10000. IDs never
  reach 20000.
- A GCEP's expert panel ID is its affiliation ID plus 30000, which puts it in the 40000
  range. A VCEP's or SC-VCEP's is its affiliation ID plus 40000, in the 50000 range. An
  independent curation group has no expert panel ID.
- Some older groups are both a VCEP and a GCEP. They're two affiliations that share an
  affiliation ID, each with its own expert panel ID. So an affiliation ID is unique per
  type, and an expert panel ID is unique.

The AS assigns both IDs when it creates an affiliation. After that, the affiliation ID,
the expert panel ID, the type, and the GPM UUID can't change, except by a superuser in
the Django admin, for fixing mistakes. A superuser's edit can't reuse another
affiliation's ID, and the last three digits of the two IDs must still match: 10042 goes
with 40042 or 50042.

**Rules.** An SC-VCEP belongs to the Somatic Cancer CDWG. An independent curation group
belongs to the CDWG named None and has no GPM UUID.

**Deleting.** Nothing in the AS is ever really deleted, since other systems, such as
curation records and the GPM, may still refer to it. Deleting an affiliation, a CDWG, a
user, or a membership marks it as deleted: it drops out of lists and searches, but it's
still found by its ID, with its history. A deleted CDWG can't get new affiliations, and
a deleted affiliation or user can't get new memberships. Deleting doesn't cascade: a
deleted user's or affiliation's memberships stay as they were, but a deleted membership
no longer counts as current. Deleted records still count for uniqueness, so a deleted
user's email or GPM UUID can't be given to someone else.

**Users and memberships.** The AS tracks each user in ClinGen's affiliations, not just
their names. An AS user is a record of someone in ClinGen's groups; it isn't a sign-in
account for ClinGen Tools, which Django's own users and `UserProfile` handle. A user has
a name, an optional preferred name, a primary email, other emails, an institution, an
ORCID iD, credentials (such as "PhD, CGC"), and an optional GPM UUID. No two users share
an email, ignoring case, whether it's their primary email or another one. A user's
primary email is optional, since some users, such as approvers in the old AS, are known
only by name. These fields are a starting point, and we expect to add more.

A membership says that a user holds a role in an affiliation. The roles are coordinator,
approver, and curator. A user who holds two roles in an affiliation has two memberships,
one per role. A membership may have a start date and an end date. It stops being current
on its end date. Ending a membership sets its end date instead of deleting it, so the AS
remembers who was in a group and when. A user can't hold the same role in the same
affiliation twice at once.

**API.** Other ClinGen tools use the AS's REST API, a Django Ninja API at `/as/api/v1/`,
with OpenAPI docs at `/as/api/v1/docs`. The version is in the path, so a breaking change
can live at `/as/api/v2/` while clients move. The API has four resources: affiliations,
users, memberships, and CDWGs. Each is addressed by its AS ID, as `/{resource}/{id}`.
Read-only lookups find affiliations by their canonical IDs:
`/affiliations/affiliation-id/{affiliation_id}` returns every affiliation with that ID
(a VCEP and a GCEP can share one), and `/affiliations/expert-panel-id/{expert_panel_id}`
returns one. Affiliations, CDWGs, and users can also be looked up by GPM UUID, as
`/{resource}/gpm-uuid/{gpm_uuid}`, and creating one with a GPM UUID that's in use is
refused. Lists are paginated, and updates use `PATCH`. A request that fails validation
gets a 422, and one that breaks a rule above gets a 400 with a `detail` message. Every
resource has a `DELETE`, which marks the record as deleted; lists leave deleted records
out unless they're asked for with `include_deleted=true`.

Clients send an API key in the `X-Api-Key` header. Any active AS key can read and change
everything in the AS; there are no read-only keys. Staff create and revoke keys in the
Django admin, which shows a new key once. The AS stores only a hash of each key.

**Staff UI.** Staff with the AS permission (`has_as_permissions`) manage affiliations,
users, memberships, and CDWGs on the AS's pages. Like the ETS's pages, they're written
for non-technical staff and never show UUIDs.

### The ClinVar Submission Service

ClinGen client systems, such as the VCI, send ClinVar records to the CSS through its
API, one at a time, and the records wait in the CSS. A staff member picks one
affiliation's waiting records, makes a batch of them, and sends the batch to the NCBI
ClinVar Submission API as one submission. The CSS polls ClinVar until the batch reaches
a final status, saves ClinVar's result for each record, and shows staff every record,
every batch, and ClinVar's responses. The CSS doesn't validate records against ClinVar's
schema beyond what it needs to store and send them, because ClinVar is the source of
truth for what's valid. It stores only the records and batches it has and ClinVar's
responses to them, not a mirror of ClinVar.

#### The ClinVar Submission API

The [ClinVar Submission API](https://www.ncbi.nlm.nih.gov/clinvar/docs/api_http/) needs
a service account for the submitting organization. Every request sends the account's API
key in the `SP-API-KEY` header. To create a submission, the CSS POSTs the ClinVar
content to `{base}/submissions/`, wrapped in an `actions` envelope (`type: AddData`,
`targetDb: clinvar`), and ClinVar returns a submission ID such as `SUB999999`. ClinVar
checks the format right away and validates the records later, so the CSS reads the
status with a GET to `{base}/submissions/SUB999999/actions/`. When processing finishes,
the status response links to a JSON summary report with each record's result and SCV
accession. A submission can hold up to 10,000 records, and records that succeed become
public in ClinVar's next weekly release.

There are two bases:

- **Production**: `https://submit.ncbi.nlm.nih.gov/api/v1`. Only prod uses it.
- **Test**: `https://submit.ncbi.nlm.nih.gov/apitest/v1`. It validates submissions fully
  but never makes them public. Dev, tools-test, and the contract tests use it.

The contract tests also use ClinVar's dry-run mode (`?dry-run=true`), which checks the
format and the API key without creating a submission. They run only when
`RUN_CONTRACT_TESTS=1` and a key is set. Unit tests use a fake client and send no
requests.

#### Batch Lifecycle

A `Batch` is one submission to ClinVar. Its slug is `B` and the start of its UUID, such
as `B3f2a9c1e`. It records its affiliation, the staff member who made it, its records,
the ClinVar submission ID, its status, ClinVar's latest response and that response's
`updated` timestamp and `errorCode`, the summary report, and any error message.

Each of a batch's records is a `Record`: one germline variant classification, with its
ClinVar JSON as the client sent it, one item of ClinVar's `germlineSubmission`. A record
is one variant-condition pair, so it has one HGVS variant, one condition, and one
observation, copied into fields that pages and search can use. A `BatchRecord` joins a
batch to each of its records in order, and holds that attempt's result from ClinVar's
summary report, so a record that fails in one batch can be tried in another. A batch
doesn't store its content: when it's sent, the CSS builds it from its records' JSON, in
order, and its assertion criteria, behalf-of organization, and release status. Choices
hold ClinVar's terms exactly; the classifications are the five ACMG terms the VCI uses.
Records extend `SlugModel` with the prefix R, since staff will refer to them as records
come to wait in the CSS for a batch. Each keeps its own ClinVar JSON, affiliation, and
client, and a status relative to the CSS's batches and ClinVar: `waiting_for_batch`
(Waiting), `in_batch` (In a Batch), `succeeded_at_clinvar` (Success, ClinVar's word), or
`withdrawn`. The client, through the API, or staff, in the CSS, can withdraw a waiting
record, and its history notes who did.

1. A client POSTs a record to the CSS API, and it waits in the CSS for a batch.
2. A staff member makes a `Batch` of one affiliation's waiting records, with status
   `not_sent_to_clinvar`. The batch copies the affiliation's settings, and its records
   are marked `in_batch`, so they can't join another batch. The CSS refuses records from
   more than one affiliation, records that aren't waiting, and more than 10,000.
3. The CSS builds the batch's content from its records and sends it to ClinVar. If
   ClinVar accepts it, the CSS saves the ClinVar submission ID, sets the status to
   `submitted_to_clinvar`, and sets `next_poll_at`. If ClinVar rejects it or can't be
   reached, the CSS sets the status to `send_to_clinvar_failed` and saves the error
   message, and the records stay in the batch to be resent.
4. The poller checks ClinVar for each `submitted_to_clinvar` or `processing_at_clinvar`
   batch whose `next_poll_at` has passed, saves the response, and either records a final
   status or pushes `next_poll_at` further out. When a batch reaches a final status, the
   poller downloads its summary report and saves each record's result.
5. Clients and staff read the status through the API or the UI at any time.

Every status names ClinVar, so it's clear which tool it's relative to: `submitted` alone
could mean submitted to the CSS. The first two are the CSS's own, for a submission
ClinVar doesn't have. The other four are ClinVar's statuses from its
[Submission API](https://www.ncbi.nlm.nih.gov/clinvar/docs/api_http/), which the poller
reads and maps onto them. Pages label each one in ClinVar's words, with ClinVar's
description in a tooltip. The statuses are:

- **`not_sent_to_clinvar`** (Not Sent): saved, but not yet sent to ClinVar. Not final.
- **`send_to_clinvar_failed`** (Send Failed): the POST to ClinVar never succeeded, so
  there's no ClinVar ID. Final; staff can resend it.
- **`submitted_to_clinvar`** (Submitted, ClinVar's `submitted`): "The submission has
  been received and is waiting to be validated." Not final.
- **`processing_at_clinvar`** (Processing, ClinVar's `processing`): "The submission is
  being validated and should be done soon." Not final.
- **`processed_by_clinvar`** (Processed, ClinVar's `processed`): "All records in the
  batch succeeded." Final.
- **`error_at_clinvar`** (Error, ClinVar's `error`): "One or more records in the batch
  failed." ClinVar's `errorCode` is 1 if some records failed and 2 if all of them did.
  Final.

`send_to_clinvar_failed` and `error_at_clinvar` stay separate: the first means ClinVar
never got the batch, and the second means ClinVar processed it and reported record
errors. The CSS never resends a batch on its own. Staff resend a
`send_to_clinvar_failed` batch from its page, which repeats step 3. A record that failed
at ClinVar goes back to waiting, where the client can replace it with a corrected
version and staff can add it to a later batch.

#### API

The API is a Django Ninja `NinjaAPI` mounted at `/css/api/v1/`, so a breaking change can
go in a new version beside it. Ninja validates request bodies and serves OpenAPI docs at
`/css/api/v1/docs`. The endpoints are:

- `POST /css/api/v1/records`: send one record to wait in the CSS for a batch. The body
  is the client's affiliation and one germline record:
  `{"affiliation": {"id": 10007, "name": "Hearing Loss VCEP"}, "record": {...}}`. The
  affiliation is the curation group whose classification the record is, with its AS ID
  and the name the client got from the AS, so the CSS can group records without reading
  the AS's data. The record must match the part of ClinVar's `germlineSubmission` schema
  the CSS models, and any other field, including the submission-level
  `assertionCriteria`, `behalfOrgID`, and `clinvarSubmissionReleaseStatus`, gets a 422.
  The CSS keeps those once per affiliation instead. The CSS saves the record as sent,
  and returns 201. If the affiliation has a waiting record with the same `localID`, the
  CSS replaces it, keeps the old version in its history, and returns 200.
- `GET /css/api/v1/records/{slug}`: read a record's affiliation, status, SCV, and JSON.
- `GET /css/api/v1/records`: list the calling client's records, newest first.
- `POST /css/api/v1/records/{slug}/withdraw`: withdraw a waiting record, so it won't be
  sent to ClinVar. A record in a batch, or one ClinVar accepted, gets a 409.

Each client system has its own API key, which it sends in the `X-API-Key` header. The
Django admin shows a new key once and stores only its hash. A client sees only its own
records; batches are the staff's. There are no webhooks: clients poll a record's GET
endpoint to learn when its status changes. The API doesn't use Clerk sessions or CSRF
protection.

#### Poller

The poller is the `poll_clinvar` management command (see Processes). Each pass, it:

- takes a few of the batches that are due
- reads each one's status from ClinVar with a request timeout, logging with the batch's
  slug
- backs off exponentially through `next_poll_at` while a batch is still processing or
  ClinVar returns an error, up to a maximum interval
- waits at least as long as ClinVar's `Retry-After` header says when ClinVar returns 429
- reports errors it catches to Sentry, so a failing batch doesn't go unnoticed, and
  moves on to the next batch
- saves each record's result from a finished batch's summary report, matched by local
  ID: a record ClinVar accepted gets its SCV, and one that failed goes back to waiting,
  so it can join a later batch, with ClinVar's errors kept on that attempt

ClinVar's processing can take days, so the poller checks on a scale of minutes, not
seconds. It keeps its state in the database, so restarting it loses nothing, and it
exits cleanly on SIGTERM after finishing the batch it's working on.

#### Staff Pages

A Records page lists every record in the CSS, newest first, with its affiliation, gene
and HGVS, classification, and status. Like the batch list, it has status pills, an
affiliation filter, a live search (gene, HGVS, local ID, or affiliation), and status
tags that link to their filter. Filtered to one affiliation, it links to that
affiliation's new batch page, where staff pick waiting records, or add every waiting
record, review them, and send them to ClinVar as one batch. The page explains in plain
words why a selection can't be batched. Each record's page shows its fields and status,
each batch it was in with ClinVar's result for it, its history in plain words, and a
Withdraw button while it waits.

The CSS's pages list every batch (a submission to ClinVar), newest first, with its
affiliation and the genes of its records. Pills filter it to one status, or show all of
them, and clicking a status tag in the table filters to that status too. A search
matches a batch's ID, ClinVar ID, or affiliation, or a record's gene or HGVS. As in the
HCI, the list is a django-tables2 table that sorts by its columns, and the search
updates the results as you type. Every status tag uses ClinVar's word for the status,
with what it means in a tooltip (`common/tooltip.html`); an Error's tooltip says whether
some or all records failed. A batch's page says in plain words what its status means and
lists its records: each one's variant, condition, classification, inheritance, date last
evaluated, whether it's new or updates an SCV, and, once ClinVar has reported, its
result in ClinVar's words (Success or Error) and its SCV. An Affiliations page lists
each affiliation that has records or batches, with a column for each pill on the Records
and Batches lists, so each count links to that list filtered to the affiliation and
status, and a gear that links to its settings. Under the CSS's title, a navbar links to
Records, Batches, and Affiliations, and each page's breadcrumbs start at its section, as
in the HCI: Records / R3f2a9c1e Details, or Records / New Batch. Both lists have an
affiliation select beside their status pills, and when a list shows one affiliation with
waiting records, a New Batch button opens its new batch page. Staff set each
affiliation's assertion criteria, on-behalf-of organization, and release status there,
once, since ClinVar applies them to a whole submission and the VCI no longer sends them.
Like the ETS's pages, they never show raw JSON or ClinVar's error text; developers see
those, and each batch's change history, in the Django admin. Staff need
`has_css_permissions`, and every staff member with it sees every batch. The page of a
`send_to_clinvar_failed` batch has a Resend button.

The CSS reads the ClinVar API key and base from the environment. It never logs the
ClinVar API key or a client's API key.

To try the workflow locally, `scripts/send_dummy_records.py` POSTs random records to a
running CSS, as the VCI would, and `CSS_SIMULATE_CLINVAR=1`, read only by the dev
settings, swaps in a simulated ClinVar. The simulator reads each batch from the
database, since the web server and the poller are separate processes. Each poll moves a
batch one step toward processed or error, and each record's result comes from a hash of
the ClinVar ID and local ID, so most records succeed and the rest fail with plausible
messages. While simulating, the dev settings shorten the poll delays to seconds, and
every CSS page shows a banner saying ClinVar is simulated.

### The Email Transfer Service

Sometimes a GCI or VCI user needs to move their account from an old email to a new one.
By then, they've usually signed in with the new email, so both emails have a Cognito
user. The old email also has a DynamoDB user record, which holds the user's history. The
new email has either no record or one with `user_status` set to `requested activation`.
The transfer keeps the old record and points it at the new email.

Before the ETS, a developer ran a script by hand to do this. The ETS turns that script
into a form ClinGen staff can use on their own. A transfer has three steps:

1. Staff enter the old and new emails.
2. The ETS checks the preconditions and shows the changes it would make, without making
   them. The preconditions are:
   - The old email has a Cognito user and a DynamoDB record.
   - The new email has a Cognito user.
   - The new email has no DynamoDB record, or one with `user_status` set to
     `requested activation`.
3. If staff confirm, the ETS makes the changes, in this order:
   1. If the new email has a `requested activation` record, retire it: set its `email`
      to `email.do.not.match`, its `user_status` to `inactive`, and its `status` to
      `deleted`.
   2. Set the `email` on the old email's DynamoDB record to the new email.
   3. Disable the old email's Cognito user.
   4. Enable the new email's Cognito user, if it isn't already enabled.

If a precondition fails, the ETS shows why and makes no changes. There's no override:
the script's `--force` flag, which skipped the `requested activation` check, has no
equivalent in the ETS. A transfer that doesn't meet the preconditions needs a developer.

Cognito and DynamoDB can't be changed in one transaction, so a transfer can fail partway
through. The ETS saves each transfer as an `EmailTransfer` record before it starts, and
records each step's result as it goes. When a step fails, the ETS stops and the record
shows which steps finished, so staff can see what's left to fix. Like every model,
`EmailTransfer` keeps its change history, so there's a record of who transferred which
email and when.

The staff who use the ETS aren't technical, so its pages describe a transfer in plain
language: a "sign-in account" instead of a Cognito user, and a "GCI/VCI profile" instead
of a DynamoDB user record. They never show PKs, Cognito usernames, attribute names, or
raw AWS errors. The `EmailTransfer` still saves those details, and developers see them
in the Django admin and in the logs.

The ETS reads its AWS credentials, region, user pool ID, and table name from the
environment, never from code. The credentials should belong to an IAM user that can do
only what a transfer needs: list, enable, and disable users in the one user pool, and
query and update items in the one table.

Until the ETS has its own AWS access, it runs in dry-run mode, which `ETS_DRY_RUN` turns
on unless it's set to `0`. A dry run checks the preconditions and records every step as
it would a real transfer, but skips the changes to AWS, and the `EmailTransfer` is
marked as a dry run.

### Color Key

Each Bulma color has one meaning, the same one it has in the HCI. Every tool follows
this key, so a color means the same thing wherever staff see it.

- **Grey** (no modifier): not finished, or neutral. Examples: debug flash messages.
- **Yellow** (`is-warning`): waiting on someone else, or caution. Examples: the
  environment banner on tools-test, the 403 and 404 pages, and warning flash messages.
- **Red** (`is-danger`): something needs fixing. Examples: form errors, error flash
  messages, and the 500 page.
- **Green** (`is-success`): done or approved. Examples: a granted permission on the
  profile page.
- **Info blue** (`is-info`): published or public. No page uses it yet, though
  `partials/messages.html` renders info flash messages in it.
- **Link blue** (`is-link`): something you can click. Examples: every button; secondary
  buttons, such as the navbar's, add `is-light`.

Status tags always render `is-light`. A status tag that's a link, such as in the CSS's
submissions table, shows its solid color on hover or focus (dark grey for a grey tag),
from `static/tools/css/custom.css`. Don't use `is-primary`. The base layout sets
`data-theme="light"`, so there is no dark theme to check.

### Confirmations

Before an action that's hard to undo, such as withdrawing a record or resending a batch,
a page asks staff to confirm in a custom modal, not with `window.confirm`. The browser's
dialog can't be styled, looks different in each browser, and some browsers let people
turn it off for a site, which would skip the question. To ask, give the form a
`data-confirm` attribute whose value is the question, in plain words:

```html
<form method="post" action="..." data-confirm="Withdraw this record?">
```

`static/tools/js/confirm-modal.js` shows the question in the Bulma modal from
`common/confirm_modal.html`, which the base layout includes on every page, and submits
the form only if staff click Confirm. Don't use `window.confirm`, `onsubmit`, or
`onclick` to ask.

### Flash Messages

Views queue flash messages only for warnings and errors. A successful action already
lands on a page that shows its result, so there are no success or info messages unless
someone explicitly asks for one.

### Processes

Gunicorn serves every tool. The CSS also needs its poller, a long-running management
command (`poll_clinvar`) that checks ClinVar for status updates. It runs as its own
systemd service next to Gunicorn, and Ansible deploys and restarts it with the web
process. Any other tool that needs background work should follow the same pattern: a
management command run by systemd, not a task queue.

### Moving the Standalone Tools

Moving a standalone tool here means porting its code into its app, moving its data into
the shared database, and pointing its clients at the new base URL. Each move is its own
epic.

The AS is the exception: it's built here from scratch rather than ported (see "The
Affiliations Service"). How the standalone AS's clients and data move to it hasn't been
designed yet. The CSS was never in production, so it has no old URLs to redirect.

## Alternatives Considered

### One Application per Tool

This is what we had: a repository, server, and deployment for each tool. It keeps the
tools fully isolated, so a bad deploy of one can't take down another. We gave it up
because the tools are small, share a stack, and are maintained by the same few people,
so the cost of maintaining each copy outweighed the isolation. The trade-off is that a
deploy or an outage now affects every tool at once.

### Separate Django Projects Behind One Caddy

Each tool could stay its own Django project on one shared server, with Caddy routing
each path prefix to that tool's Gunicorn. This saves on servers but not on maintenance:
there'd still be one set of dependencies, settings, and migrations per tool. One project
gets us the savings we want.

### Subdomains Instead of Path Prefixes

Each tool could have its own subdomain (as.tools.clinicalgenome.org, for example). Path
prefixes need only one DNS record and one TLS certificate, and they let staff sign in
once for every tool, so we chose them.

## Cross-Cutting Concerns

### Isolation Between Tools

Every tool runs in the same process and shares one database, so a slow query or a crash
in one tool affects the others. Tests for each tool must pass on their own, and
`just ci` runs every tool's tests on every change, including changes that touch only one
tool.

### Backups

Each server backs up its database to its own S3 bucket, as the HCI does. Every deploy
takes a backup just before it migrates; see `docs/how-to.md`. One database means one
backup covers every tool.

### Error Monitoring and Uptime

Sentry captures unhandled exceptions from every tool in one Sentry project. Each event
is tagged with the tool that raised it, so we can filter by tool. UptimeRobot monitors
the landing page and each tool's prefix separately, so an alert names the tool that's
down.
