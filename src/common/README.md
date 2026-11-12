# `common`

This app holds code and templates shared by more than one tool. Tools may import from
it, but it never imports from a tool. It holds what the landing page and base layout
need, and pieces every tool's pages use, such as breadcrumbs; more moves here from the
HCI and the CSS when a tool needs it.

### `__init__.py`

Empty file that marks `common` as a Python package.

### `breadcrumbs.py`

Builds the breadcrumb trail at the top of each tool's pages, like the HCI's: a section's
list page, then an object's page, then the current page, such as Affiliation Search /
Kidney Cystic GCEP / Edit. There's no Home crumb, since the site navbar links home. Each
view passes its trail to its template as `breadcrumbs`, built with `section()`,
`detail()`, and `action()`.

### `context_processors.py`

Adds `GIT_SHA` (the deployed commit, shown in the footer) and `ENV` (the environment
name, used by the environment banner) to every template's context.

### `middleware.py`

Defines `ToolTagMiddleware`, which tags each Sentry event with the tool that handled the
request (`as`, `css`, or `ets`), taken from the resolved URL's namespace. Requests
outside a tool, such as the landing page and sign-in, get no tag.

### `templates/common/breadcrumbs.html`

Renders `breadcrumbs` as a Bulma breadcrumb, with the current page last, bold, and not a
link elsewhere. Each tool's header includes it under its navbar.

### `templates/common/confirm_modal.html`

The Bulma modal card that `tools/js/confirm-modal.js` shows before submitting a form
with a `data-confirm` attribute. `layouts/base.html` includes it once on every page.

### `templates/common/icon.html`

Renders a Bootstrap Icons icon. Pass the icon's name as `icon_name`.

### `templates/common/tooltip.html`

A Tippy.js tooltip, ported from the HCI. Callers pass `text` and optional `classes`, and
either `icon_name`, for an icon with no visible text, or `label`, which puts the tooltip
on the label itself, such as a tag, and with `href` makes the label a link. Either is
keyboard-focusable and keeps the arrow cursor, since the browser would show the text
cursor over a label, and the text is also in an `is-sr-only` span for screen readers.
`tools/js/tooltips.js` attaches the tooltip.

### `models.py`

Defines the abstract models every tool's models extend: `UUIDModel`, which gives a model
a random UUID primary key, and `SlugModel`, which adds a unique slug made from the
model's `slug_prefix` and the first 8 hex characters of its UUID. If a new object's slug
is taken, `SlugModel` gives it a new UUID. `make_slug()` builds the slug, and
`set_unique_slugs()` sets them for objects saved with `bulk_create()`, which skips
`save()`.

### `tests/__init__.py`

Marks `tests` as a Python package.

### `tests/test_breadcrumbs.py`

Tests the crumb helpers in `breadcrumbs.py`, and that `common/breadcrumbs.html` links
every crumb but the current page and renders nothing without a trail.

### `tests/test_middleware.py`

Tests that `ToolTagMiddleware` tags tool requests and leaves other requests untagged,
through a test URLconf, defined in this file, that adds a fake ETS to the project's
URLconf.

### `tests/test_models.py`

Tests that `make_slug()` builds a slug.

### `tests/test_templates.py`

Tests that the tooltip template puts its text in a focusable tooltip, on an icon or a
label, and the base layout loads Tippy.js, and that every page has the confirmation
modal and no template asks with `window.confirm`.
