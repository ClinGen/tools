# `affiliations_service`

This app is the Affiliations Service (AS), mounted at `/as/` with the URL namespace
`as`. It's the source of truth for ClinGen and non-ClinGen users and groups working in
ClinGen apps: the users in ClinGen's affiliations, the affiliations themselves, and the
CDWGs they belong to. Only users with `has_as_permissions` can use its pages. "The
Affiliations Service" in `docs/design.md` describes its design.

### `__init__.py`

Empty file that marks `affiliations_service` as a Python package.

### `admin.py`

Registers CDWGs and affiliations in the Django admin, with their history. ClinVar
submitter IDs are edited inline on their affiliation, and other emails inline on their
user. Memberships are edited inline on both affiliations and users. Admin search finds a
user by any of their emails. Creating an API key shows the raw key once, in a message,
since only its hash is stored. Only superusers can change an existing affiliation's IDs,
type, and GPM UUID.

### `api/__init__.py`

Marks `api` as a Python package.

### `api/affiliations.py`

Serves `/affiliations`. The list is paginated, leaves out deleted affiliations unless
`include_deleted` is true, filters by type, status, CDWG, affiliation ID, and expert
panel ID, and searches names with `q`. Creating one assigns its IDs, so a request can't
send them. `PATCH` can't change the IDs, type, or GPM UUID, and sending
`clinvar_submitter_ids` replaces the list. `DELETE` marks the affiliation deleted.
Read-only lookups find affiliations by affiliation ID
(`/affiliation-id/{affiliation_id}`, which returns every affiliation sharing it) and
expert panel ID (`/expert-panel-id/{expert_panel_id}`). An affiliation can also be
found, changed, and deleted by GPM UUID (`/gpm-uuid/{gpm_uuid}`). Responses for one
affiliation include its current memberships.

### `api/auth.py`

Defines `ApiKeyAuth`, which accepts a request whose `X-Api-Key` header is an active AS
API key.

### `api/cdwgs.py`

Serves `/cdwgs`: list (paginated), get, create, update (`PATCH`), and delete CDWGs, and
find, change, and delete one by GPM UUID (`/gpm-uuid/{gpm_uuid}`). A CDWG that any
affiliation belongs to can't be deleted.

### `api/helpers.py`

Holds `save_validated`, which applies changes to a model instance, runs `full_clean()`,
and saves it, so every endpoint checks the same rules as the admin and the staff UI.

### `api/memberships.py`

Serves `/memberships`: list (paginated, filtered by affiliation, user, role, and
`current`), get, create, and `PATCH` for the dates. Setting `end_date` ends a
membership, and `DELETE` deletes it. A deleted affiliation can't get new members.

### `api/users.py`

Serves `/users`: list (paginated, with `q` searching names and every email, and exact
filters for `email`, `orcid`, and `gpm_uuid`), get, create, and update (`PATCH`).
Sending `other_emails` replaces the list. A user can also be found, changed, and deleted
by GPM UUID (`/gpm-uuid/{gpm_uuid}`). `DELETE` deletes a user, with their memberships
and other emails. Responses for one user include their current memberships.

### `api/v1.py`

Defines the AS's API, a Django Ninja `NinjaAPI` served at `/as/api/v1/`, with OpenAPI
docs at `/as/api/v1/docs`. Every endpoint needs an API key. It adds each resource's
router and turns a `ValidationError` (a broken business rule) into a 400 whose `detail`
is the error's plain-language message. Its docs write acronyms such as ID, GPM, UUID,
and CDWG in capitals, since Ninja would otherwise make titles like "Gpm Uuid" from
Python names.

### `apps.py`

Configures the `affiliations_service` app.

### `forms.py`

Defines the forms on the AS's pages: `AffiliationCreateForm` (which can also make picked
users the new affiliation's coordinators), `AffiliationEditForm` (which leaves out the
IDs, type, and GPM UUID, so posting them changes nothing), and `SubmitterIdFormSet` for
an affiliation's ClinVar submitter IDs, `UserForm`, and `OtherEmailFormSet` for a user's
other emails, and `MembershipAddForm`, which also checks the membership constraints that
Django would skip because the affiliation isn't a form field, and `CDWGForm`.
`BulmaFormMixin` gives text inputs Bulma's classes.

### `history.py`

Describes an object's change history in plain language, such as "Changed Status from
Applying to Active.", for the AS's pages. It shows choice labels instead of stored
values and names instead of IDs.

### `management/__init__.py`

Marks `management` as a Python package.

### `management/commands/__init__.py`

Marks `commands` as a Python package.

### `management/commands/import_old_as.py`

Defines `import_old_as`, which copies CDWGs, affiliations, and users from the old AS
using the key in `AS_API_KEY`. `--dry-run` shows what it would do without saving.

From the old AS's API (`cdwg_list/` and `database_list/`), it imports CDWGs,
affiliations with their IDs, deleted flags, and ClinVar submitter IDs, and coordinators
and approvers as users with memberships. Users are matched by email, then by name, so an
approver who is also a coordinator becomes one user. Rerunning it updates only what
changed. Records that break the AS's rules are imported anyway, with a warning.

### `models.py`

Defines `CDWG`, `Affiliation`, and `ClinVarSubmitterId`. An affiliation's IDs are
assigned when it's created: the affiliation ID counts up from 10000, and the expert
panel ID is the affiliation ID plus 30000 for a GCEP or 40000 for a VCEP or SC-VCEP.
Affiliations delete softly: `SoftDeleteMixin` and `SoftDeleteQuerySet` make deleting
one, alone or in a queryset, mark it deleted instead, and `objects.active()` leaves
deleted ones out. A new membership can't go to a deleted affiliation. CDWGs, users, and
memberships are really deleted, and their history keeps what they held; deleting a user
deletes their memberships and other emails. `Affiliation.clean()` checks the business
rules (an SC-VCEP's CDWG, an independent curation group's CDWG and GPM UUID) and that
hand-set IDs are in range and end in the same three digits. Constraint and uniqueness
errors have plain-language messages, so forms can show them to staff.

It also defines `User` and `UserEmail` (a user's other emails). A user's main email is
optional, but no two users share an email, ignoring case, whether it's a primary or
another email: constraints catch duplicates within each table, and `clean()` catches
them across the two, and a user's other email that repeats their main one. ORCID iDs are
checked for format and are unique when set.

Finally, it defines `Membership`: a user's role (coordinator, approver, or curator) in
an affiliation, with optional start and end dates. A user can't hold the same role in
the same affiliation twice at once, and an end date can't come before its start date.
`Membership.objects.current()` returns memberships that haven't ended, and `end()` ends
one by setting its end date instead of deleting it.

`ApiKey` is the key a client system sends to use the API. Raw keys start with `as_`, and
only their SHA-256 hash and first eight characters are stored. `ApiKey.objects.verify()`
finds the active key for a raw value and records its use.

### `static/affiliations_service/formset.js`

Adds a blank row to a formset when staff click its Add Another button, by copying the
formset's empty-form `<template>` and bumping its `TOTAL_FORMS`.

### `tables.py`

Defines the django-tables2 tables for the affiliation, user, and CDWG lists. Like the
HCI's, they sort by their column headers and show 100 rows per page. The views keep the
search and filters, so paging and sorting keep them.

### `templates/affiliations_service/affiliation_delete.html`

Asks staff to confirm deleting an affiliation, and explains that the AS keeps it. The
affiliation's page asks in the confirmation modal instead; this page is for when
JavaScript is off.

### `templates/affiliations_service/affiliation_detail.html`

An affiliation's page: its fields, ClinVar submitter IDs, current members by role, past
members, and history, with Edit and Delete buttons. Delete asks in the confirmation
modal, then posts to the delete page. It says so if the affiliation was deleted.

### `templates/affiliations_service/affiliation_form.html`

The form for creating or editing an affiliation, with its ClinVar submitter IDs. When
creating, staff can search for users and check the affiliation's coordinators. When
editing, it shows the IDs, type, and whether it's linked to the GPM as read-only.

### `templates/affiliations_service/cdwg_form.html`

The form for adding or editing a CDWG.

### `templates/affiliations_service/cdwg_list.html`

Lists the CDWGs, with a search box, and how many affiliations each has, linking to the
affiliation list filtered by that CDWG, and a pencil icon in the Edit column to edit
each one. CDWGs aren't deleted from the UI, since affiliations need them.

### `templates/affiliations_service/index.html`

The AS's home page, which lists affiliations. Its search box and filters update the list
with HTMX as staff type, and work as a plain form without JavaScript.

### `templates/affiliations_service/partials/field.html`

Renders one form field with its label, help text, and errors in Bulma's style.

### `templates/affiliations_service/partials/formset.html`

Renders an inline formset of one-field rows, such as ClinVar submitter IDs or other
emails, with an Add Another button and the blank row it copies. The rows have a bottom
margin, so the button doesn't touch the last one.

### `templates/affiliations_service/partials/formset_row.html`

One row of `partials/formset.html`: the field, its errors, and a Remove checkbox for
saved rows. The rows have a bottom margin so the button doesn't touch them.

### `templates/affiliations_service/partials/header.html`

The AS's title and subtitle, then its navbar, copied from the HCI's: Affiliations,
CDWGs, and Users dropdowns, each with Search and Add links, and a burger menu on narrow
screens, then the page's breadcrumbs. Every AS page includes it.

### `templates/affiliations_service/partials/history.html`

A table of the changes in `history`, from `history.describe_history()`.

### `templates/affiliations_service/partials/members.html`

An affiliation's members section: current members by role, each with an End button that
asks in the confirmation modal, the Add a Member form, and past members. HTMX swaps the
whole section after adding or ending a membership.

### `templates/affiliations_service/partials/navbar_link.html`

One navbar link, in bold when it's the current page. Pass `url` (a URL name) and `text`.

### `templates/affiliations_service/partials/status.html`

An affiliation's status as a tag: green for active, yellow for applying, and grey
otherwise.

### `templates/affiliations_service/partials/user_choices.html`

The user search's results: radio buttons for the add-member form, checkboxes for the
new-affiliation form's coordinators, or a link to add a user when no one matches.

### `templates/affiliations_service/user_detail.html`

A user's page: their details, other emails, current and past affiliations (linking to
each), and history.

### `templates/affiliations_service/user_form.html`

The form for adding or editing a user, with their other emails.

### `templates/affiliations_service/user_list.html`

Lists users, with a search box for names and emails that updates the list with HTMX.

### `tests/__init__.py`

Marks `tests` as a Python package.

### `tests/helpers.py`

Helpers shared by the AS's tests: `make_staff`, which makes a staff user with or without
`has_as_permissions`, and `FLAVOR_TEXT`, the AS's description.

### `tests/test_admin.py`

Tests the AS's admin pages: showing a new API key once, membership inlines, user search,
and which affiliation fields are locked for non-superusers.

### `tests/test_affiliation_forms.py`

Tests creating, editing, and deleting affiliations on the AS's pages, including locked
fields, submitter IDs, plain-language errors, permissions, and picking coordinators on
the new-affiliation form.

### `tests/test_affiliation_pages.py`

Tests the affiliation list's search and filters and the affiliation page's members,
history, and deleted notice, and that both need `has_as_permissions` and hide UUIDs.

### `tests/test_api_affiliations.py`

Tests the API's affiliation endpoints: filters, deleted affiliations, ID assignment,
business rules, locked fields, submitter IDs, soft deletion, and 404s.

### `tests/test_api_cdwgs.py`

Tests the API's CDWG endpoints. Its `ApiTestCase` sends every request with an active API
key; the other API tests extend it.

### `tests/test_api_docs.py`

Tests the AS API's docs: that records are addressed by `{id}` and lookups by their ID
names, that titles and summaries capitalize acronyms, and that schema names capitalize
CDWG.

### `tests/test_api_gpm_uuids.py`

Tests the API's GPM UUID endpoints: looking up, changing, and deleting affiliations,
CDWGs, and users by GPM UUID, the 404 for an unknown one, that locked affiliation fields
can't change, and that creating a record with a GPM UUID in use is refused.

### `tests/test_api_keys.py`

Tests API keys: hashing, verification, the 401 for a missing, unknown, or inactive key,
and the public docs.

### `tests/test_api_lookups.py`

Tests the lookups by affiliation ID, which return every affiliation sharing it, and by
expert panel ID, and that they're read-only.

### `tests/test_api_memberships.py`

Tests the API's membership endpoints: filters, creating, ending, constraint errors, no
delete, and the current memberships in affiliation and user responses.

### `tests/test_api_users.py`

Tests the API's user endpoints: search and filters, other emails, duplicate emails,
ORCID iD checks, 404s, and that users can't be deleted.

### `tests/test_cdwg_pages.py`

Tests the CDWG list's counts, links, and search, adding and editing CDWGs, and the error
for a name that differs from another only in case.

### `tests/test_deleting.py`

Tests deleting through the API: CDWGs, users, and memberships are deleted and leave
history, deleting a user deletes their memberships and emails, a CDWG with affiliations
can't be deleted, and affiliations are still only marked deleted.

### `tests/test_formsets.py`

Tests the Add Another rows on the affiliation and user forms: that each form offers
them, and that two new submitter IDs posted at once are both saved.

### `tests/test_index.py`

Tests the AS's home page, including that it requires `has_as_permissions`, and that the
landing page links to the AS.

### `tests/test_member_pages.py`

Tests adding and ending memberships from an affiliation's page, with and without HTMX,
and the user search behind the add-member form.

### `tests/test_memberships.py`

Tests membership roles, constraints, which memberships are current, ending a membership,
and history.

### `tests/test_models.py`

Tests ID assignment, soft deletion, uniqueness constraints, and history.

### `tests/test_navigation.py`

Tests that every AS page has the navbar's Search and Add links, that the current page's
link is bold, and the breadcrumb trails.

### `tests/test_old_as_import.py`

Tests the old AS import with a fake fetch: what it imports, how it matches users, that
reruns change nothing, dry runs, and rule warnings.

### `tests/test_pagination.py`

Tests paging and sorting the affiliation list, that paging keeps the search and filters,
and that the user and CDWG lists page too.

### `tests/test_rules.py`

Tests the business rules in `Affiliation.clean()`, the ID checks, and the plain-language
uniqueness errors.

### `tests/test_user_pages.py`

Tests the users list's search, a user's page, and adding and editing users and their
other emails, including duplicate emails and bad ORCID iDs.

### `tests/test_users.py`

Tests users's email uniqueness, ORCID iD checks, GPM UUIDs, and history.

### `urls.py`

Routes the AS's pages under `/as/` (an affiliation's page is
`/as/affiliations/<uuid>/`), and its API under `/as/api/v1/`.

### `views.py`

Defines the AS's pages: the affiliation list, an affiliation's page, and the pages that
create, edit, and delete an affiliation. Deleting marks it deleted. It also has the
users list, a user's page, and the pages that add and edit a user. The membership views
add a member to an affiliation and end a membership, returning the updated members
section to HTMX requests, and `user_search` finds users for the add-member form.
`_save_form_and_formset` saves an object and its inline formset together, or neither.
Each view requires `has_as_permissions`.
