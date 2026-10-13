# UI/UX overhaul plan (M9) — status and next steps

Approved 2026-10-13. Phases 1–3 are built and pushed (eb5778d); **phases 4–5 are built** (see below); **phase 6 is next**. A fresh session should read this file, then `docs/HANDOFF.md`.

## Goal (user's words, condensed)

A **fast, functional, visually better version of the current Wagtail CMS with better UX** — not a rebrand. Editors must be able to edit step output as rich text (headings, lists, bold, italic, underline, links by type, anchors, embeds, drag-and-drop images with alt text, tables, FAQ) with a Visual/Markdown toggle, and everything Wagtail already does must keep working. The company CMS ("Article and News Page", screenshots in the 2026-10-13 session) is **inspiration only**, not a sync target.

## Decisions

| Topic | Decision |
|---|---|
| Stored format | Markdown stays the format every step reads and writes. Dialect: [ADR 0007](adr/0007-markdown-dialect.md) |
| Editor | **Tiptap v3 (3.32.0, MIT) + official `@tiptap/markdown`**, vanilla UI (no React), vendored esbuild bundle. Draftail rejected (Draft.js format, archived, no underline/tables); Toast UI archived; Milkdown Crepe was the runner-up |
| Choosers | Reuse Wagtail 8's `window.PageChooserModal`, `ImageChooserModal`, `DocumentChooserModal` (`new X(url).open(opts, callback)`); jQuery + `modal-workflow.js` are already on admin pages, add the three `*-chooser-modal.js` via `forms.Media` |
| Theme | Palette B (graphite + one teal accent), light and dark, through Wagtail CSS variables only (`apps/brand/static/brand/theme.css`). Outfit for headings (self-hosted TTF, OFL). **No custom branding**: Wagtail's logo, titles and sign-in wording stay (user reverted the "Content Studio" rebrand) |
| Page model | ArticlePage: intro, category (Article/News), tags, author snippet, figure/embed/FAQ blocks, heading anchors; scheduling uses Wagtail's `go_live_at` |

## Status

| Phase | State | Where |
|---|---|---|
| 1 Dialect + renderers | **Done** | `apps/content/dialect.py`, `apps/content/markup.py` (`render`, `WagtailResolver`, `strip_dialect`, `resolve_references`), prompts `_rules.md`/`draft.md`, `tests/test_dialect.py`, fixture `tests/fixtures/dialect/article.md` |
| 2 Page model, publishing, exports | **Done** | `apps/content/blocks.py`, `models.py` (Author, ArticlePageTag), migration `content/0002`, `apps/content/wagtail_hooks.py` (underline + sanitiser rules), `markup.build_article`, `publishing.py`, `exports.py`, templates `content/blocks/*`, `tests/test_publish.py` |
| 3 Admin theme | **Done** (branding reverted) | `apps/brand/` (theme.css, font, hook), dashboard panels in `apps/studio/wagtail_hooks.py` + `studio/home/*.html`, `tests/test_theme.py` |
| 4 Toolchain + core editor | **Done** | `frontend/` (`src/schema.js`, `nodes.js`, `editor.js`, `editor.css`, `test/roundtrip.test.js`), Dockerfile `frontend` stage, dev service `frontend`, CI job `frontend`, `services.save_edit`, `run_workspace.html`, `tests/test_editing.py` |
| 5 Wagtail integrations | **Done** | `apps/studio/views/editor_api.py` (upload, refs, embed), `frontend/src/{links,media,slash,wagtail,ui}.js`, migration `studio/0005`, `WAGTAILEMBEDS_FINDERS`, `tests/test_editor_api.py`, `frontend/test/phase5.test.js` |
| 6 Polish | **Next** | see below |

Also done after phase 3: upload limits of **10 MB per image and 25 MB per document (PDF)** (settings + `tests/test_security.py::test_upload_size_limits`; Caddy request cap 30 MB). **SVG and WebP images** (user spec 2026-10-13): WebP is a Wagtail default; SVG added to `WAGTAILIMAGES_EXTENSIONS`, sandboxed by a CSP header on media, rasterised for DOCX (`tests/test_image_formats.py`).

Deferred from phase 3 into phase 4 (the run workspace template is rewritten there anyway): move the studio templates' inline `style=` attributes into `studio.css` classes, add hover/active/focus and loading/empty/error states per the redesign-skill audit, sentence-case copy, `tabular-nums` on metrics.

## Phase 4 — toolchain and core editor

Built on 2026-10-13. Deviations from the plan below: Tiptap is pinned at **3.31.3** (3.32.0 was released the same day; the rule is versions at least two weeks old), vitest 5.0.1, happy-dom 20.14.5, esbuild 0.28.2. The FAQ is one `faq` container node (questions are `###` headings inside it) rather than `faq`/`faqItem`: it round-trips the dialect exactly and keeps editing simple. Inline images the dialect doesn't model are kept verbatim (`rawInline`). Findings from round-tripping the real step outputs in the database: `*` bullets become `-`, trailing spaces go, tables are padded, a list right after a paragraph line becomes a real list (as CommonMark reads it); the server renders the rest identically. Fixed on the server along the way: heading ids picked up Python-Markdown placeholders for entities (`&amp;`), `\~`/`\+` weren't escapes, and escaped quotes stayed in captions. Not verifiable in the built-in browser pane (no animation frames there): the scroll to the editor on **Edit**.

The original plan:

1. `frontend/`: `package.json` (exact pins: `@tiptap/core`, `@tiptap/starter-kit`, `@tiptap/markdown`, `@tiptap/extension-underline`, `-link`, `-table`/`-table-row`/`-table-cell`/`-table-header`, `-placeholder`, `-file-handler`, `@tiptap/suggestion`; dev: `esbuild`, `vitest`, `happy-dom`), committed `package-lock.json`, `build.mjs` (ESM, minified, metafile), `src/`, `test/`.
2. Output `apps/studio/static/studio/editor/editor.{js,css}` (git-ignored). Dockerfile: first stage `FROM node:24-alpine` (pin digest) runs `npm ci && npm run build`; runtime stage `COPY --from=frontend` **before** `collectstatic`. Dev: compose service `frontend` (`npm run watch`, profile `dev`) writing into the bind mount (the dev mount `.:/app` hides image-built files). CI job `frontend` (build, vitest, gzip budget ≤ 250 KB).
3. Editor mounts on the existing `<textarea name="content">` in `run_workspace.html`; if the bundle is missing the textarea still works. StarterKit limited to H2–H4, Underline (`++`), Link, Table (inline-only cells), Markdown; custom nodes with their own `parseMarkdown`/`renderMarkdown`: `wagtailImage`, `embed`, `faq`/`faqItem`, `verify` chip (`[VERIFY]` never escaped). Heading ids via `frontend/src/slug.js` mirroring `dialect.slugify`.
4. UX: **Edit** swaps the rendered output for the editor in place; sticky toolbar, bubble menu, Visual/Markdown toggle (Markdown mode = the textarea); actions **Save as new version** (`action=save_version`), **Save and approve** (`edit_approve`), **Cancel**; both post `base_version`. Only serialise when the editor is dirty (Tiptap normalises LLM Markdown). localStorage autosave `studio:draft:{run}:{step}:{base}` + restore banner; `beforeunload` guard.
5. Server: `services.save_edit(step, user, content, base_version)` (READY only, `ValueError` if a newer version exists, no-op if unchanged, `Source.EDIT`); same base check in `approve_step`; add `save_version` to `permissions.can_act` (same rule as approve).
6. Tests: vitest parse→serialise idempotence over `tests/fixtures/dialect/*.md`; pytest `save_edit` (permissions, conflict, unchanged) with `Client(enforce_csrf_checks=True)`; a view test posting `edit_approve` (none exists yet).

## Phase 5 — Wagtail integrations

Built on 2026-10-14 and verified in the browser on a throwaway run: page link through Wagtail's page chooser, image from the library chooser with alt text and caption, pasted image uploaded with required alt text, `/` menu, YouTube embed checked through oEmbed, saved version rendered by the server. Notes:

- Wagtail's chooser modals can't sit on top of a modal `<dialog>`, so the link and image dialogs close before the chooser opens and the choice is applied when it returns.
- Choosing an image prefills alt text from the image's description in the library; uploads store the alt text as the description.
- Writers got add and choose rights for images and documents on the root collection (Wagtail lets owners change their own uploads, not other people's). Editors already had them.
- Not built: link previews on hover and a keyboard-shortcut help; both move to phase 6.

The original plan:

- `apps/studio/views/editor_api.py` under `studio/editor/` (JSON, `permissions.ACCESS` + Wagtail permission policies, CSRF from `wagtailConfig.CSRF_TOKEN`):
  - `POST images/` (file, alt, decorative) through Wagtail's image form, so the limits apply (**10 MB per image**, `WAGTAILIMAGES_MAX_UPLOAD_SIZE`; documents/PDFs **25 MB**, `WAGTAILDOCS_MAX_UPLOAD_SIZE`; Caddy allows 30 MB per request for form overhead). Accept AVIF, GIF, JPEG, PNG, WebP and SVG (`accept=` on the file input from `WAGTAILIMAGES_EXTENSIONS`); SVG previews use the original (no raster rendition). Show the limit and the types in the drop zone and a clear error when a file is too big. `description=alt`; returns `{id, ref, preview_url, width, height}`.
  - `GET refs/?image=..&page=..&document=..` batched titles/previews (reuse `markup.WagtailResolver`).
  - `GET embed/?url=` via `wagtail.embeds.get_embed` (title + thumbnail); restrict `WAGTAILEMBEDS_FINDERS` to oEmbed YouTube/Vimeo.
- Editor: link popover types URL / page / document / #anchor (from the document's headings) / mailto / tel; image drag/paste/upload with alt-text dialog (required unless decorative) and caption, plus "choose existing"; embed and FAQ nodes; `/` slash menu; shortcuts.
- Data migration: Writers/Editors get image and document collection add/choose permissions.
- Tests: endpoint 403s per role, upload validation, JSON shape.

## Phase 6 — polish

Also in scope since 2026-10-14: link titles on hover in the editor, a shortcut list, and moving the remaining inline `style=` attributes in the studio templates into `studio.css`.


Word-level and rendered diff in `VersionCompareView`; keyboard-shortcut help; update `docs/user-guide.md` (editing), `docs/development.md` (frontend build), `docs/workflow.md` (dialect vs the skills, per CLAUDE.md), the handbook artifact.

## Verification (end to end, after 4–5)

Edit run 11's research visually (heading, list, underline, page link, #anchor, dragged image with alt, YouTube embed, FAQ), toggle Markdown↔Visual with no diff, save as a new version, approve, run through draft → publish; the Wagtail page shows figure/alt/caption, embed, FAQ, intro, category, tags; DOCX/HTML exports contain them. Screenshots in light and dark via the built-in browser.

## Risks

- Tiptap rewrites LLM Markdown (bullets, escapes): dirty-flag-only serialisation, `verify` node, tolerant `VERIFY_RE`, fixture suite.
- `@tiptap/markdown` is an early release: exact pins, custom node serialisers, CI fixtures, textarea fallback.
- Wagtail upgrades: `tests/test_theme.py` fails if an overridden variable disappears.
