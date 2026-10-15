# `core`

This app holds the pages that belong to no tool. For now that's the landing page at `/`,
which links to each tool.

### `__init__.py`

Empty file that marks `core` as a Python package.

### `apps.py`

Configures the `core` app.

### `templates/core/home.html`

The landing page. Lists each mounted tool with its name, abbreviation, link, and
description, or says that no tools are available yet.

### `tests.py`

Tests the landing page with no tools mounted and with a fake ETS mounted (through test
URLconfs, defined in this file, that take the project's URLconf without its tools),
tests `get_tool()`, and tests that the 404 and 500 pages render their templates.

### `tools.py`

Lists every tool ClinGen Tools houses, with its name, abbreviation, URL namespace, and
description. `get_tool()` returns one by its URL namespace, so a tool's pages can reuse
its name and description. `mounted_tools()` returns only the tools whose URLconf is
mounted, so the landing page never links to a page that doesn't exist. Add a tool here
when you add its app.

### `urls.py`

Routes `/` to the landing page.

### `views.py`

Renders the landing page with the mounted tools.
