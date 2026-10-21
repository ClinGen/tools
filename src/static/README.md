# `static`

This directory holds the static files Django serves. The files under `tools/` are
vendored from `node_modules` or bundled from `src/auth_/js/` by `build.js`
(`just js-build`); don't edit them by hand. To upgrade one, update `package.json` and
rerun `just js-build`. The exceptions are `tools/css/custom.css` and
`tools/js/tooltips.js`, which we wrote.

### `tools/css/bootstrap-icons.css`

The Bootstrap Icons stylesheet.

### `tools/css/bulma.css`

The Bulma CSS framework.

### `tools/css/tippy.css`

The Tippy.js stylesheet, for tooltips.

### `tools/css/custom.css`

Our own styles, which Bulma has no class for: a status tag that's a link shows its solid
color, without `is-light`, on hover or keyboard focus, using the variables Bulma's color
classes set. A grey tag turns dark grey, since a plain tag is as light as `is-light`.

### `tools/css/fonts/bootstrap-icons.woff`

The Bootstrap Icons font, in WOFF format.

### `tools/css/fonts/bootstrap-icons.woff2`

The Bootstrap Icons font, in WOFF2 format.

### `tools/js/callback.js`

The bundled Clerk token-exchange script for the sign-in callback page, built from
`src/auth_/js/callback.jsx`.

### `tools/js/htmx.js`

HTMX, for partial page updates.

### `tools/js/popper.min.js`

Popper, which positions Tippy.js's tooltips. Tippy needs it loaded first.

### `tools/js/popper.min.js.map`

Popper's source map, which `collectstatic` needs.

### `tools/js/sign-in.js`

The bundled Clerk sign-in widget, built from `src/auth_/js/sign-in.jsx`.

### `tools/js/tippy.umd.min.js`

Tippy.js, for tooltips.

### `tools/js/tippy.umd.min.js.map`

Tippy.js's source map, which `collectstatic` needs.

### `tools/js/tooltips.js`

Adds a Tippy.js tooltip to every element with a `data-tippy-content` attribute,
including elements HTMX swaps in later. Screen readers get the text from the element's
`is-sr-only` span instead, so Tippy doesn't add `aria-describedby`. Ported from the HCI.
