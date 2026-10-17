# `clinvar_submission_service`

This app is the ClinVar Submission Service (CSS), mounted at `/css/` with the URL
namespace `css`. It forwards ClinGen clients' submissions to ClinVar and tracks each one
until ClinVar has processed it. Only users with `has_css_permissions` can use its pages.
"The ClinVar Submission Service" in `docs/design.md` describes how a submission moves
through the CSS.

### `__init__.py`

Empty file that marks `clinvar_submission_service` as a Python package.

### `admin.py`

Registers `Submission` in the Django admin, with its history. ClinVar's fields are
read-only, since only ClinVar's responses should change them.

### `apps.py`

Configures the `clinvar_submission_service` app.

### `models.py`

Defines `Submission`, one request to ClinVar: the payload as the client sent it, the
ClinVar submission ID, its status, ClinVar's latest response, `updated` timestamp, error
code, and summary report, any error message, and when it was last and will next be
polled. It extends `common.models.SlugModel`, so its ID is a UUID and its slug is `S`
and the first 8 hex characters of the UUID, such as `S3f2a9c1e`. It keeps its change
history. `Submission.objects.due_to_poll()` returns the submitted and processing
submissions whose next poll time has passed.

### `templates/clinvar_submission_service/index.html`

The CSS's home page, with its name and description from `core.tools`.

### `tests.py`

Tests the `Submission` slug, including a colliding one, its default status, and its
history; which submissions are due to poll; the admin pages; and that only users with
CSS permissions can open the home page, which the landing page links to.

### `urls.py`

Routes the CSS's pages under the `css` namespace: the home page.

### `views.py`

Serves the CSS's pages to users with CSS permissions.
