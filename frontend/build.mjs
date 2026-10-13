// Bundles the editor into apps/studio/static/studio/editor/ (git-ignored; built by the Dockerfile's
// frontend stage, the dev compose service `frontend`, or `npm run build`). `--watch` rebuilds on change.

import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import * as esbuild from "esbuild";

const here = dirname(fileURLToPath(import.meta.url));
const outdir = join(here, "..", "apps", "studio", "static", "studio", "editor");
const watch = process.argv.includes("--watch");

const options = {
  // editor.js imports editor.css, so esbuild writes editor.js and editor.css side by side.
  entryPoints: { editor: join(here, "src", "editor.js") },
  outdir,
  bundle: true,
  minify: !watch,
  sourcemap: watch ? "inline" : false,
  format: "iife",
  target: ["es2022"],
  legalComments: "eof",
  metafile: true,
  logLevel: "info",
};

mkdirSync(outdir, { recursive: true });
if (watch) {
  const context = await esbuild.context(options);
  await context.watch();
} else {
  const result = await esbuild.build(options);
  writeFileSync(join(here, "meta.json"), JSON.stringify(result.metafile));
}
