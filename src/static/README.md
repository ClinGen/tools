# `static`

This directory holds the static files Django serves. The files under `tools/` are
vendored from `node_modules` by `build.js` (`just js-build`); don't edit them by hand.
To upgrade one, update `package.json` and rerun `just js-build`.

### `tools/css/bootstrap-icons.css`

The Bootstrap Icons stylesheet.

### `tools/css/bulma.css`

The Bulma CSS framework.

### `tools/css/fonts/bootstrap-icons.woff`

The Bootstrap Icons font, in WOFF format.

### `tools/css/fonts/bootstrap-icons.woff2`

The Bootstrap Icons font, in WOFF2 format.

### `tools/js/htmx.js`

HTMX, for partial page updates.
