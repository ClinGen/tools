# `auth_`

This app signs staff in with Clerk and checks each tool's permission. It's ported from
the HCI's `auth_` app, without the HCI's PHI agreement and curation permissions. The
Clerk application is shared with ClinGen's other apps.

Each tool has a boolean permission flag on `UserProfile`. Staff grant flags in the
Django admin, and every change is recorded in the profile's history.

### `__init__.py`

Empty file that marks `auth_` as a Python package.

### `admin.py`

Registers `UserProfile` in the Django admin, with its change history, so staff can
grant tool permissions. Unregisters Django's groups, which we don't use.

### `apps.py`

Configures the `auth_` app.

### `backends.py`

Defines `ClerkBackend`, which finds or creates the Django user for a verified Clerk user.
It matches by Clerk user ID first, then links an existing user with the same email, and
otherwise creates a new user with no tool permissions.

### `js/callback.jsx`

Loads Clerk on the callback page so it can exchange a URL-delivered token for a session
cookie, then returns to the callback view. `build.js` bundles it into
`src/static/tools/js/callback.js`.

### `js/sign-in.jsx`

Renders Clerk's sign-in widget and sends the user to the callback view once they've
signed in. `build.js` bundles it into `src/static/tools/js/sign-in.js`.

### `models.py`

Defines `UserProfile`, which links a Django user to a Clerk user ID and holds one
permission flag per tool, starting with `has_ets_permissions`. Add a flag here when you
add a tool that needs one.

### `permissions.py`

Checks a tool's permission flag. Use `ToolPermissionMixin` (set `tool_permission`) for
class-based views and `tool_permission_required` for function-based views. Anonymous
users are sent to sign in; signed-in users without the flag get a 403. Naming a flag
that doesn't exist raises `ImproperlyConfigured`.

### `templates/auth_/callback.html`

A bare page that loads the Clerk token-exchange script.

### `templates/auth_/login.html`

The sign-in page, which hosts Clerk's sign-in widget.

### `tests.py`

Tests the permission mixin and decorator, permission history, the Clerk backend, and
the login, callback, and logout views. Clerk is mocked; no test calls Clerk's servers.

### `urls.py`

Routes `login`, `callback`, and `logout` under `/auth/`.

### `views.py`

Defines the sign-in, callback, and sign-out views. The login view remembers a local
`next` URL so the callback can return the user to the page they asked for. The callback
verifies Clerk's session token, looks up the user's primary email, and signs them in.
Sign-out only accepts POST, and it revokes the Clerk session before ending the Django
session.
