# UI/UX overhaul plan (M9) — status and next steps

Approved 2026-10-13. Phases 1–3 are built and pushed (eb5778d); **phases 4–6 are next**. A fresh session should read this file, then `docs/HANDOFF.md`.

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
| 4 Toolchain + core editor | **Next** | see below |
| 5 Wagtail integrations | Planned | see below |
| 6 Polish | Planned | see below |

Deferred from phase 3 into phase 4 (the run workspace template is rewritten there anyway): move the studio templates' inline `style=` attributes into `studio.css` classes, add hover/active/focus and loading/empty/error states per the redesign-skill audit, sentence-case copy, `tabular-nums` on metrics.

## Phase 4 — toolchain and core editor

1. `frontend/`: `package.json` (exact pins: `@tiptap/core`, `@tiptap/starter-kit`, `@tiptap/markdown`, `@tiptap/extension-underline`, `-link`, `-table`/`-table-row`/`-table-cell`/`-table-header`, `-placeholder`, `-file-handler`, `@tiptap/suggestion`; dev: `esbuild`, `vitest`, `happy-dom`), committed `package-lock.json`, `build.mjs` (ESM, minified, metafile), `src/`, `test/`.
2. Output `apps/studio/static/studio/editor/editor.{js,css}` (git-ignored). Dockerfile: first stage `FROM node:24-alpine` (pin digest) runs `npm ci && npm run build`; runtime stage `COPY --from=frontend` **before** `collectstatic`. Dev: compose service `frontend` (`npm run watch`, profile `dev`) writing into the bind mount (the dev mount `.:/app` hides image-built files). CI job `frontend` (build, vitest, gzip budget ≤ 250 KB).
3. Editor mounts on the existing `<textarea name="content">` in `run_workspace.html`; if the bundle is missing the textarea still works. StarterKit limited to H2–H4, Underline (`++`), Link, Table (inline-only cells), Markdown; custom nodes with their own `parseMarkdown`/`renderMarkdown`: `wagtailImage`, `embed`, `faq`/`faqItem`, `verify` chip (`[VERIFY]` never escaped). Heading ids via `frontend/src/slug.js` mirroring `dialect.slugify`.
4. UX: **Edit** swaps the rendered output for the editor in place; sticky toolbar, bubble menu, Visual/Markdown toggle (Markdown mode = the textarea); actions **Save as new version** (`action=save_version`), **Save and approve** (`edit_approve`), **Cancel**; both post `base_version`. Only serialise when the editor is dirty (Tiptap normalises LLM Markdown). localStorage autosave `studio:draft:{run}:{step}:{base}` + restore banner; `beforeunload` guard.
5. Server: `services.save_edit(step, user, content, base_version)` (READY only, `ValueError` if a newer version exists, no-op if unchanged, `Source.EDIT`); same base check in `approve_step`; add `save_version` to `permissions.can_act` (same rule as approve).
6. Tests: vitest parse→serialise idempotence over `tests/fixtures/dialect/*.md`; pytest `save_edit` (permissions, conflict, unchanged) with `Client(enforce_csrf_checks=True)`; a view test posting `edit_approve` (none exists yet).

## Phase 5 — Wagtail integrations

- `apps/studio/views/editor_api.py` under `studio/editor/` (JSON, `permissions.ACCESS` + Wagtail permission policies, CSRF from `wagtailConfig.CSRF_TOKEN`):
  - `POST images/` (file, alt, decorative) through Wagtail's image form (size/type limits), `description=alt`; returns `{id, ref, preview_url, width, height}`.
  - `GET refs/?image=..&page=..&document=..` batched titles/previews (reuse `markup.WagtailResolver`).
  - `GET embed/?url=` via `wagtail.embeds.get_embed` (title + thumbnail); restrict `WAGTAILEMBEDS_FINDERS` to oEmbed YouTube/Vimeo.
- Editor: link popover types URL / page / document / #anchor (from the document's headings) / mailto / tel; image drag/paste/upload with alt-text dialog (required unless decorative) and caption, plus "choose existing"; embed and FAQ nodes; `/` slash menu; shortcuts.
- Data migration: Writers/Editors get image and document collection add/choose permissions.
- Tests: endpoint 403s per role, upload validation, JSON shape.

## Phase 6 — polish

Word-level and rendered diff in `VersionCompareView`; keyboard-shortcut help; update `docs/user-guide.md` (editing), `docs/development.md` (frontend build), `docs/workflow.md` (dialect vs the skills, per CLAUDE.md), the handbook artifact.

## Verification (end to end, after 4–5)

Edit run 11's research visually (heading, list, underline, page link, #anchor, dragged image with alt, YouTube embed, FAQ), toggle Markdown↔Visual with no diff, save as a new version, approve, run through draft → publish; the Wagtail page shows figure/alt/caption, embed, FAQ, intro, category, tags; DOCX/HTML exports contain them. Screenshots in light and dark via the built-in browser.

## Risks

- Tiptap rewrites LLM Markdown (bullets, escapes): dirty-flag-only serialisation, `verify` node, tolerant `VERIFY_RE`, fixture suite.
- `@tiptap/markdown` is an early release: exact pins, custom node serialisers, CI fixtures, textarea fallback.
- Wagtail upgrades: `tests/test_theme.py` fails if an overridden variable disappears.
