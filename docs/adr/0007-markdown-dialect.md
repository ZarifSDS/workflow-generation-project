# ADR 0007: One Markdown dialect for the editor, the prompts and the renderers

- Status: Accepted
- Date: 2026-10-13

## Context

Every pipeline step stores Markdown, and later steps, publishing and exports all read it. The rich-text editor (plan: Tiptap with Markdown) adds things plain Markdown can't express: images from the Wagtail library with alt text and captions, embeds, FAQ blocks, underline, heading anchors, and links to Wagtail pages and documents. Those have to survive the round trip through the editor, through later model steps, and into the published page and exports.

## Decision

The studio's Markdown is CommonMark plus GFM tables, with these additions (implemented in `apps/content/dialect.py`):

| Construct | Syntax |
|---|---|
| Headings | `##`–`####` in the body; `#` stays the page title |
| Heading anchor | `## Safety data sheets {#sds}`. Without `{#…}` the id is generated: ASCII-folded, lowercase, non-alphanumerics become `-`, repeats get `-2`, `-3` (`dialect.slugify`, mirrored in the editor) |
| Underline / strikethrough | `++text++` / `~~text~~` |
| Links | `https:`, `mailto:`, `tel:`, `#anchor`, `wagtail://page?id=12`, `wagtail://document?id=7` |
| Image (block) | `![Alt text](wagtail://image?id=42 "Caption")`; the title is the caption |
| Decorative image | `![](wagtail://image?id=42&decorative=1 "Caption")`; empty alt without it is reported |
| Embed | `![Title](wagtail://media?url=<percent-encoded URL>)` on its own line |
| FAQ | `:::faq`, then per item `### Question?` and answer paragraphs, then `:::` |
| Claims to check | `[VERIFY]`, also counted when escaped as `\[VERIFY\]` |

- The `wagtail://` references are exactly the format Wagtail 8 uses for rich text in Markdown (`wagtail.admin.rich_text.converters.markdown_db.wagtail_ref`), checked by a contract test.
- Rendering has two modes. **html** resolves references through a batched resolver (`markup.WagtailResolver`: image renditions, page and document URLs, absolute for exports). Missing objects degrade to plain text and are reported as warnings. **stream** keeps the references for building StreamField blocks.
- Sanitising stays strict. The nh3 allowlist adds `u s figure figcaption img section`, `id` on h2–h4 and `tel:` links. Images load only from our own resolved URLs (raw `<img>` in model output is dropped), and no iframes are ever produced: embeds render as links in the admin and in exports.
- Prompts tell models to keep these constructs exactly (`apps/studio/prompts/_rules.md`) and how to write an FAQ (`draft.md`). Metrics run on `markup.strip_dialect(...)` so syntax doesn't count as words.

## Consequences

- One shared fixture set (`tests/fixtures/dialect/`) defines the expected behaviour; the editor's round-trip tests use the same files.
- Underline (`++…++`) and `{#id}` aren't standard GFM; other Markdown tools show them literally. Exports render them properly.
- A deleted image or page shows up as a warning instead of a broken link or image.
