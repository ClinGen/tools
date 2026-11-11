# `affiliations_service`

This app is the Affiliations Service (AS), mounted at `/as/` with the URL namespace
`as`. It's the source of truth for ClinGen affiliations, the CDWGs they belong to, and
the people who hold roles in them. Only users with `has_as_permissions` can use its
pages. "The Affiliations Service" in `docs/design.md` describes its design.

### `__init__.py`

Empty file that marks `affiliations_service` as a Python package.

### `api/__init__.py`

Marks `api` as a Python package.

### `api/people.py`

Serves `/people`: list (paginated, with `q` searching names and every email, and exact
filters for `email`, `orcid`, and `gpm_uuid`), get, create, and update (`PATCH`).
Sending `other_emails` replaces the list. There's no delete, since people stay on
record.

### `api/v1.py`

Defines the AS's API, a Django Ninja `NinjaAPI` served at `/as/api/v1/`, with OpenAPI
docs at `/as/api/v1/docs`. Every endpoint needs an API key. It adds each resource's
router and turns a `ValidationError` (a broken business rule) into a 400 whose `detail`
is the error's plain-language message.

### `api/affiliations.py`

Serves `/affiliations`. The list is paginated, leaves out deleted affiliations unless
`include_deleted` is true, filters by type, status, CDWG, affiliation ID, and expert
panel ID, and searches names with `q`. Creating one assigns its IDs, so a request can't
send them. `PATCH` can't change the IDs, type, or GPM UUID, and sending
`clinvar_submitter_ids` replaces the list. `DELETE` marks the affiliation deleted.

### `api/auth.py`

Defines `ApiKeyAuth`, which accepts a request whose `X-Api-Key` header is an active AS
API key.

### `api/cdwgs.py`

Serves `/cdwgs`: list (paginated), get, create, and update (`PATCH`) CDWGs.

### `api/helpers.py`

Holds `save_validated`, which applies changes to a model instance, runs `full_clean()`,
and saves it, so every endpoint checks the same rules as the admin and the staff UI.

### `admin.py`

Registers CDWGs and affiliations in the Django admin, with their history. ClinVar
submitter IDs are edited inline on their affiliation, and other emails inline on their
person. Memberships are edited inline on both affiliations and people. Admin search
finds a person by any of their emails. Creating an API key shows the raw key once, in a
message, since only its hash is stored. Only superusers can change an existing
affiliation's IDs, type, and GPM UUID.

### `apps.py`

Configures the `affiliations_service` app.

### `models.py`

Defines `CDWG`, `Affiliation`, and `ClinVarSubmitterId`. An affiliation's IDs are
assigned when it's created: the affiliation ID counts up from 10000, and the expert
panel ID is the affiliation ID plus 30000 for a GCEP or 40000 for a VCEP or SC-VCEP.
Deleting an affiliation, alone or in a queryset, marks it deleted instead, and
`Affiliation.objects.active()` leaves deleted ones out. `Affiliation.clean()` checks the
business rules (an SC-VCEP's CDWG, an independent curation group's CDWG and GPM UUID)
and that hand-set IDs are in range and end in the same three digits. Constraint and
uniqueness errors have plain-language messages, so forms can show them to staff.

It also defines `Person` and `PersonEmail` (a person's other emails). No two people
share an email, ignoring case, whether it's a primary or another email: constraints
catch duplicates within each table, and `clean()` catches them across the two. ORCID iDs
are checked for format and are unique when set.

Finally, it defines `Membership`: a person's role (coordinator, approver, or curator) in
an affiliation, with optional start and end dates. A person can't hold the same role in
the same affiliation twice at once, and an end date can't come before its start date.
`Membership.objects.current()` returns memberships that haven't ended, and `end()` ends
one by setting its end date instead of deleting it.

`ApiKey` is the key a client system sends to use the API. Raw keys start with `as_`, and
only their SHA-256 hash and first eight characters are stored. `ApiKey.objects.verify()`
finds the active key for a raw value and records its use.

### `templates/affiliations_service/index.html`

The AS's home page.

### `templates/affiliations_service/partials/header.html`

The AS's title, description, and tabs, shared by its pages. Pages pass `active_tab` to
highlight their tab.

### `test_api_affiliations.py`

Tests the API's affiliation endpoints: filters, deleted affiliations, ID assignment,
business rules, locked fields, submitter IDs, soft deletion, and 404s.

### `test_api_cdwgs.py`

Tests the API's CDWG endpoints. Its `ApiTestCase` sends every request with an active API
key; the other API tests extend it.

### `test_api_keys.py`

Tests API keys: hashing, verification, the 401 for a missing, unknown, or inactive key,
the public docs, and showing a new key once in the admin.

### `test_api_people.py`

Tests the API's person endpoints: search and filters, other emails, duplicate emails,
ORCID iD checks, 404s, and that people can't be deleted.

### `test_memberships.py`

Tests membership roles, constraints, which memberships are current, ending a membership,
history, and the admin inlines.

### `test_models.py`

Tests ID assignment, soft deletion, uniqueness constraints, and history.

### `test_people.py`

Tests people's email uniqueness, ORCID iD checks, GPM UUIDs, history, and admin search.

### `test_rules.py`

Tests the business rules in `Affiliation.clean()`, the ID checks, the plain-language
uniqueness errors, and which fields the admin locks for non-superusers.

### `tests.py`

Tests the AS's pages, including that they require `has_as_permissions`, and that the
landing page links to the AS.

### `urls.py`

Routes the AS's pages under `/as/`, and its API under `/as/api/v1/`.

### `views.py`

Defines the AS's pages. Each view requires `has_as_permissions`.
