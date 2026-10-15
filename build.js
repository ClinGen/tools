/**
 * Copies our JavaScript and CSS dependencies into the static directory where Django
 * expects them to be. This script assumes you're in the root directory of the
 * repository.
 */

import { copyFile, mkdir } from "node:fs/promises";
import * as esbuild from "esbuild";

const CSS_STATIC_DIR = "./src/static/tools/css";
const JS_STATIC_DIR = "./src/static/tools/js";

await mkdir(`${CSS_STATIC_DIR}/fonts`, { recursive: true });
await mkdir(JS_STATIC_DIR, { recursive: true });

// Bundle the Clerk React components for the sign-in pages. Note that esbuild, unlike
// some other bundlers, doesn't bundle unless you ask it to, hence bundle: true.
await esbuild.build({
  entryPoints: ["./src/auth_/js/sign-in.jsx", "./src/auth_/js/callback.jsx"],
  outdir: JS_STATIC_DIR,
  bundle: true,
  platform: "browser",
  format: "iife",
  target: "es2020",
  minify: true,
  define: {
    "process.env.NODE_ENV": '"production"',
  },
});

// Copy HTMX into our Django static directory.
const htmxPath = "./node_modules/htmx.org/dist/htmx.min.js";
await copyFile(htmxPath, `${JS_STATIC_DIR}/htmx.js`);

// Copy Bulma into our Django static directory.
const bulmaPath = "./node_modules/bulma/css/bulma.min.css";
await copyFile(bulmaPath, `${CSS_STATIC_DIR}/bulma.css`);

// Copy Bootstrap Icons CSS into our Django static directory.
const bootstrapIconsCssPath =
  "./node_modules/bootstrap-icons/font/bootstrap-icons.min.css";
await copyFile(bootstrapIconsCssPath, `${CSS_STATIC_DIR}/bootstrap-icons.css`);

// Copy Bootstrap Icons fonts into our Django static directory.
const bootstrapIconsFontsPath = "./node_modules/bootstrap-icons/font/fonts";
await copyFile(
  `${bootstrapIconsFontsPath}/bootstrap-icons.woff`,
  `${CSS_STATIC_DIR}/fonts/bootstrap-icons.woff`,
);
await copyFile(
  `${bootstrapIconsFontsPath}/bootstrap-icons.woff2`,
  `${CSS_STATIC_DIR}/fonts/bootstrap-icons.woff2`,
);
