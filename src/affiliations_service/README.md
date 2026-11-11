# `affiliations_service`

This app is the Affiliations Service (AS), mounted at `/as/` with the URL namespace
`as`. It's the source of truth for ClinGen affiliations, the CDWGs they belong to, and
the people who hold roles in them. Only users with `has_as_permissions` can use its
pages. "The Affiliations Service" in `docs/design.md` describes its design.

### `__init__.py`

Empty file that marks `affiliations_service` as a Python package.

### `admin.py`

Registers CDWGs and affiliations in the Django admin, with their history. ClinVar
submitter IDs are edited inline on their affiliation.

### `apps.py`

Configures the `affiliations_service` app.

### `models.py`

Defines `CDWG`, `Affiliation`, and `ClinVarSubmitterId`. An affiliation's IDs are
assigned when it's created: the affiliation ID counts up from 10000, and the expert
panel ID is the affiliation ID plus 30000 for a GCEP or 40000 for a VCEP or SC-VCEP.
Deleting an affiliation, alone or in a queryset, marks it deleted instead, and
`Affiliation.objects.active()` leaves deleted ones out.

### `templates/affiliations_service/index.html`

The AS's home page.

### `templates/affiliations_service/partials/header.html`

The AS's title, description, and tabs, shared by its pages. Pages pass `active_tab` to
highlight their tab.

### `test_models.py`

Tests ID assignment, soft deletion, uniqueness constraints, and history.

### `tests.py`

Tests the AS's pages, including that they require `has_as_permissions`, and that the
landing page links to the AS.

### `urls.py`

Routes the AS's pages under `/as/`.

### `views.py`

Defines the AS's pages. Each view requires `has_as_permissions`.
