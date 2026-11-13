# `core`

This app holds the pages that belong to no tool. For now that's the landing page at `/`,
which links to each tool.

### `__init__.py`

Empty file that marks `core` as a Python package.

### `apps.py`

Configures the `core` app.

### `templates/core/home.html`

The landing page. Lists each tool the user may see with its name, abbreviation, link, and
description, or says that no tools are available yet.

### `tests/__init__.py`

Marks `tests` as a Python package.

### `tests/test_tools.py`

Tests `get_tool()` and which tools need a permission to be seen.

### `tests/test_views.py`

Tests the landing page with no tools mounted and with a fake ETS mounted (through test
URLconfs, defined in this file, that take the project's URLconf without its tools), that
it shows the ETS only to users with ETS permissions and the AS and the CSS to everyone,
and that the 404 and 500 pages render their templates.

### `tools.py`

Lists every tool ClinGen Tools houses, with its name, abbreviation, URL namespace,
description, the page the landing page links to (its `index` unless it names another,
as the CSS names its records list), and the `UserProfile` flag a person needs to see it,
if any (only the ETS has one). `get_tool()` returns one by its URL namespace, so a
tool's pages can reuse its name and description. `visible_tools()` returns only the
tools whose URLconf is mounted and that the user may see, so the landing page never
links to a page that doesn't exist or hides the ETS from people who can't use it. Add a
tool here when you add its app.

### `urls.py`

Routes `/` to the landing page.

### `views.py`

Renders the landing page with the tools the user may see.
