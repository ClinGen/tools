# `affiliations_service`

This app is the Affiliations Service (AS), mounted at `/as/` with the URL namespace
`as`. It's the source of truth for users and groups inside and outside of ClinGen apps:
the people in ClinGen's affiliations, the affiliations themselves, and the CDWGs they
belong to. Only users with `has_as_permissions` can use its pages. "The Affiliations
Service" in `docs/design.md` describes its design.

### `__init__.py`

Empty file that marks `affiliations_service` as a Python package.

### `api/__init__.py`

Marks `api` as a Python package.

### `api/memberships.py`

Serves `/memberships`: list (paginated, filtered by affiliation, person, role, and
`current`), get, create, and `PATCH` for the dates. Setting `end_date` ends a
membership; there's no delete. A deleted affiliation can't get new members.

### `api/people.py`

Serves `/people`: list (paginated, with `q` searching names and every email, and exact
filters for `email`, `orcid`, and `gpm_uuid`), get, create, and update (`PATCH`).
Sending `other_emails` replaces the list. There's no delete, since people stay on
record. Responses for one person include their current memberships.

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
Responses for one affiliation include its current memberships.

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

### `breadcrumbs.py`

Builds the breadcrumb trail at the top of each AS page, like the HCI's: the list page,
the object's page, and the current action. There's no Home crumb, since the site navbar
links home. Each view passes its trail to its template as `breadcrumbs`.

### `forms.py`

Defines the forms on the AS's pages: `AffiliationCreateForm` (which can also make picked
people the new affiliation's coordinators), `AffiliationEditForm` (which leaves out the
IDs, type, and GPM UUID, so posting them changes nothing), and `SubmitterIdFormSet` for
an affiliation's ClinVar submitter IDs, `PersonForm`, and `OtherEmailFormSet` for a
person's other emails, and `MembershipAddForm`, which also checks the membership
constraints that Django would skip because the affiliation isn't a form field, and
`CdwgForm`. `BulmaFormMixin` gives text inputs Bulma's classes.

### `history.py`

Describes an object's change history in plain language, such as "Changed Status from
Applying to Active.", for the AS's pages. It shows choice labels instead of stored
values and names instead of IDs.

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
catch duplicates within each table, and `clean()` catches them across the two, and a
person's other email that repeats their main one. ORCID iDs are checked for format and
are unique when set.

Finally, it defines `Membership`: a person's role (coordinator, approver, or curator) in
an affiliation, with optional start and end dates. A person can't hold the same role in
the same affiliation twice at once, and an end date can't come before its start date.
`Membership.objects.current()` returns memberships that haven't ended, and `end()` ends
one by setting its end date instead of deleting it.

`ApiKey` is the key a client system sends to use the API. Raw keys start with `as_`, and
only their SHA-256 hash and first eight characters are stored. `ApiKey.objects.verify()`
finds the active key for a raw value and records its use.

### `static/affiliations_service/formset.js`

Adds a blank row to a formset when staff click its Add Another button, by copying the
formset's empty-form `<template>` and bumping its `TOTAL_FORMS`.

### `templates/affiliations_service/affiliation_delete.html`

Asks staff to confirm deleting an affiliation, and explains that the AS keeps it.

### `templates/affiliations_service/affiliation_detail.html`

An affiliation's page: its fields, ClinVar submitter IDs, current members by role, past
members, and history, with Edit and Delete buttons. It says so if the affiliation was
deleted.

### `templates/affiliations_service/affiliation_form.html`

The form for creating or editing an affiliation, with its ClinVar submitter IDs. When
creating, staff can search for people and check the affiliation's coordinators. When
editing, it shows the IDs, type, and whether it's linked to the GPM as read-only.

### `templates/affiliations_service/cdwg_form.html`

The form for adding or editing a CDWG.

### `templates/affiliations_service/cdwg_list.html`

Lists the CDWGs, with a search box, and how many affiliations each has, linking to the
affiliation list filtered by that CDWG. CDWGs aren't deleted from the UI, since
affiliations need them.

### `templates/affiliations_service/index.html`

The AS's home page, which lists affiliations. Its search box and filters update the list
with HTMX as staff type, and work as a plain form without JavaScript.

### `templates/affiliations_service/partials/header.html`

The AS's title and subtitle, then its navbar, copied from the HCI's: Affiliations,
People, and CDWGs dropdowns, each with Search and Add links, and a burger menu on narrow
screens, then the page's breadcrumbs. Every AS page includes it.

### `test_affiliation_forms.py`

Tests creating, editing, and deleting affiliations on the AS's pages, including locked
fields, submitter IDs, plain-language errors, permissions, and the Add Another button on
the affiliation and person forms, and picking coordinators on the new-affiliation form.

### `test_affiliation_pages.py`

Tests the affiliation list's search and filters and the affiliation page's members,
history, and deleted notice, and that both need `has_as_permissions` and hide UUIDs.

### `test_api_affiliations.py`

Tests the API's affiliation endpoints: filters, deleted affiliations, ID assignment,
business rules, locked fields, submitter IDs, soft deletion, and 404s.

### `test_api_cdwgs.py`

Tests the API's CDWG endpoints. Its `ApiTestCase` sends every request with an active API
key; the other API tests extend it.

### `test_api_keys.py`

Tests API keys: hashing, verification, the 401 for a missing, unknown, or inactive key,
the public docs, and showing a new key once in the admin.

### `test_api_memberships.py`

Tests the API's membership endpoints: filters, creating, ending, constraint errors, no
delete, and the current memberships in affiliation and person responses.

### `test_api_people.py`

Tests the API's person endpoints: search and filters, other emails, duplicate emails,
ORCID iD checks, 404s, and that people can't be deleted.

### `test_member_pages.py`

Tests adding and ending memberships from an affiliation's page, with and without HTMX,
and the person search behind the add-member form.

### `test_cdwg_pages.py`

Tests the CDWG list's counts and links, adding and editing CDWGs, and the error for a
name that differs from another only in case.

### `test_memberships.py`

Tests membership roles, constraints, which memberships are current, ending a membership,
history, and the admin inlines.

### `test_models.py`

Tests ID assignment, soft deletion, uniqueness constraints, and history.

### `test_navigation.py`

Tests that every AS page has the navbar's Search and Add links, that the current page's
link is bold, the CDWG list's search, and the breadcrumb trails.

### `test_people.py`

Tests people's email uniqueness, ORCID iD checks, GPM UUIDs, history, and admin search.

### `test_people_pages.py`

Tests the people list's search, a person's page, and adding and editing people and their
other emails, including duplicate emails and bad ORCID iDs.

### `test_rules.py`

Tests the business rules in `Affiliation.clean()`, the ID checks, the plain-language
uniqueness errors, and which fields the admin locks for non-superusers.

### `templates/affiliations_service/person_detail.html`

A person's page: their details, other emails, current and past affiliations (linking to
each), and history.

### `templates/affiliations_service/person_form.html`

The form for adding or editing a person, with their other emails.

### `templates/affiliations_service/person_list.html`

Lists people, with a search box for names and emails that updates the list with HTMX.

### `templates/affiliations_service/partials/breadcrumbs.html`

Renders `breadcrumbs` as a Bulma breadcrumb, with the current page last, bold, and not a
link elsewhere. `partials/header.html` includes it under the navbar.

### `templates/affiliations_service/partials/field.html`

Renders one form field with its label, help text, and errors in Bulma's style.

### `templates/affiliations_service/partials/navbar_link.html`

One navbar link, in bold when it's the current page. Pass `url` (a URL name) and `text`.

### `templates/affiliations_service/partials/members.html`

An affiliation's members section: current members by role, each with an End button, the
Add a Member form, and past members. HTMX swaps the whole section after adding or ending
a membership.

### `templates/affiliations_service/partials/formset.html`

Renders an inline formset of one-field rows, such as ClinVar submitter IDs or other
emails, with an Add Another button and the blank row it copies. The rows have a bottom
margin, so the button doesn't touch the last one.

### `templates/affiliations_service/partials/formset_row.html`

One row of `partials/formset.html`: the field, its errors, and a Remove checkbox for
saved rows. The rows have a bottom margin so the button doesn't touch them.

### `templates/affiliations_service/partials/history.html`

A table of the changes in `history`, from `history.describe_history()`.

### `templates/affiliations_service/partials/person_choices.html`

The person search's results: radio buttons for the add-member form, checkboxes for the
new-affiliation form's coordinators, or a link to add a person when no one matches.

### `templates/affiliations_service/partials/status.html`

An affiliation's status as a tag: green for active, yellow for applying, and grey
otherwise.

### `tests.py`

Tests the AS's pages, including that they require `has_as_permissions`, and that the
landing page links to the AS.

### `urls.py`

Routes the AS's pages under `/as/` (an affiliation's page is
`/as/affiliations/<uuid>/`), and its API under `/as/api/v1/`.

### `views.py`

Defines the AS's pages: the affiliation list, an affiliation's page, and the pages that
create, edit, and delete an affiliation. Deleting marks it deleted. It also has the
people list, a person's page, and the pages that add and edit a person. The membership
views add a member to an affiliation and end a membership, returning the updated members
section to HTMX requests, and `person_search` finds people for the add-member form.
`_save_form_and_formset` saves an object and its inline formset together, or neither.
Each view requires `has_as_permissions`.
