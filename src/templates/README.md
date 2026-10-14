# `templates`

This directory holds the project-wide templates: the base layout every page extends, its
partials, and the error pages.

### `403.html`

The page shown when a user doesn't have permission to see a page.

### `404.html`

The page shown when a page doesn't exist.

### `500.html`

The page shown when the server hits an unhandled error. Django renders it without a
request context, so it must not depend on context processors.

### `layouts/base.html`

The base layout. Loads Bulma, Bootstrap Icons, and HTMX, sends the CSRF token with every
HTMX request, and lays out the header, messages, main content, and footer.

### `partials/env_banner.html`

A banner shown on every environment except production, naming the environment.

### `partials/footer.html`

The footer, with the copyright line and the deployed commit.

### `partials/messages.html`

Renders Django's flash messages, one Bulma message per flash message.

### `partials/navbar.html`

The navigation bar, with a link to the landing page.
