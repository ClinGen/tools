# `common`

This app holds code and templates shared by more than one tool. Tools may import from
it, but it never imports from a tool. For now it holds only what the landing page and
base layout need; more moves here from the HCI and the CSS when a tool needs it.

### `__init__.py`

Empty file that marks `common` as a Python package.

### `context_processors.py`

Adds `GIT_SHA` (the deployed commit, shown in the footer) and `ENV` (the environment
name, used by the environment banner) to every template's context.

### `middleware.py`

Defines `ToolTagMiddleware`, which tags each Sentry event with the tool that handled the
request (`as`, `css`, or `ets`), taken from the resolved URL's namespace. Requests
outside a tool, such as the landing page and sign-in, get no tag.

### `templates/common/icon.html`

Renders a Bootstrap Icons icon. Pass the icon's name as `icon_name`.

### `tests.py`

Tests that `ToolTagMiddleware` tags tool requests and leaves other requests untagged
(through a test URLconf, defined in this file, that adds a fake ETS to the project's
URLconf), and that backups go to a local directory and are named with the subdomain.
