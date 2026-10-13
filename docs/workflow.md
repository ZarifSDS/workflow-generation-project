# Content workflow

The studio automates an existing, proven manual workflow that runs as a set of Claude Code skills (`ehs-seo-blog-optimized`, `ehs-outbound-blog`, `deslop`, `clarity-review`, `clean-user-facing-text`, `sds-hero-stock`). The app keeps its structure: **each phase produces an artefact, and you approve it before the next phase starts.**

## Brief (inputs)

| Field | Meaning |
|---|---|
| Type | `seo_blog` (for sdsmanager.com; includes pillar pages), `outbound` (guest post), `lead_magnet`, `whitepaper` |
| TOPIC | What the piece is about |
| PKEYWORD / SKEYWORD | Primary keyword and secondary keywords |
| WORDCOUNT | Target length |
| FKGL | Target Flesch-Kincaid grade level |
| AUDIENCE | Who it is for (e.g. EHS managers) |
| REGION | Market, for spelling, regulation and localisation (US, UK, AU, CA, NZ…) |
| SITE, SITE_DOMAIN, NARRATIVE_MODE | Outbound pieces only: target site and its voice. NARRATIVE_MODE is proposed by the site crawl step |
| Preset | Optional. Saved defaults for a content type (region, FKGL, audience, CTA style, model per step), e.g. "SDS Manager blog · US · FKGL 9" |

## Pipeline steps

| # | Step | Output | Gate | Default profile |
|---|---|---|---|---|
| 0 | Accuracy gate (planned, not built) | Findings: apply-now vs confirm-first | Approve | quality |
| 0b | Site crawl (guest posts only) | Site profile: narrative mode, voice, heading style, typical length, reading level, link habits; list of pages read or skipped | Approve (edit allowed) | none (fetching) + fast (summarising) |
| 1 | Research | Sources, claims, verification table | Approve | fast |
| 2 | Outline | Detailed outline + headings-only outline + structure decisions | Approve (edit allowed) | quality |
| 3 | Draft | Full draft, three metadata options per field, link map | Approve (optionally per H2) | quality |
| 4 | Review and edit | Revised article plus a per-section changelog and grade report ([sequence below](#review-and-edit-step-m5)) | Approve | edit |
| 5 | Final cleanup | Hidden-Unicode removal, final mechanical sweep | Auto | none (deterministic) |
| 6 | Hero image | Generated photo, vision check, branded hero ([details below](#hero-image-step-m6)) | Approve | image + vision |
| 7 | Localise (optional) | Regional or language variants | Approve | quality |
| 8 | Publish | `ArticlePage` draft → Wagtail moderation workflow; exports ([details below](#publish-step-m7)) | Approve, then the Wagtail workflow | none |

**Profiles** map to a provider and model in configuration (see [providers.md](providers.md)):

- `quality`: slower, best writing
- `fast`: quick extraction and summaries
- `edit`: targeted revision in the review-and-edit step (may differ from the drafting model)
- `image`: hero image generation
- `vision`: looks at the generated hero photo (subject position, readable text, safety problems)

## Review and edit step (M5)

This replaces Step 3 of the blog skills with the sequence used in practice:

1. **Per-section grade scan:** FKGL for every H2 section, shown as a table and badges.
2. **De-slop pass:** the `deslop` mechanisms (lexical, structure and redundancy scans, then a rewrite of what they flag).
3. **Clarity review:** the `clarity-review` checks (repeated sentence frames, unclear references, jargon).
4. **Strip meta narration** ("In this article we'll…", "Let's dive in", "As mentioned above", and similar).
5. **Sections above grade 13:** word-level edits first. No sentence splitting at this stage.
6. **Re-scan** the per-section grade.
7. **Targeted splits:** split only sentences whose split drastically lowers the section's grade while keeping clarity. Each candidate split is shown with its before and after grade.
8. **Approval**, with a changelog of every edit by section.

Each sub-step's output and grade change is visible on the run screen. Sub-steps 2, 3, 5 and 7 use the `edit` profile. M5 also adds an **edit round** to the model evaluation, since the best editing model may differ from the best drafting model.

## Approval actions and UI (M3–M4)

On each step awaiting approval you can:

- **Approve:** accept the output and queue the next step.
- **Edit & approve:** change the output in the admin editor, then continue. Your edited version is what later steps see.
- **Regenerate:** rerun the step. A **provider and model dropdown** lists only models verified as available, marked free or paid, with the step's default profile preselected.
- **Reject:** stop the run and record why.

**Title, meta description and slug options** from the draft step appear as a **checklist**. Tick the options you want, or use **"Add your own"** to type a custom option into the list. Whatever is ticked or typed is used by later steps and the published page.

## Reusing the existing skill scripts (M5–M6)

The skills already contain deterministic Python helpers. The studio will vendor and wrap these rather than reimplement them, keeping attribution and running them as quality checks:

| Skill | Scripts | Used for |
|---|---|---|
| deslop | `lexical_scan.py`, `structure_scan.py`, `redundancy_scan.py` | AI-tell and redundancy badges after drafting and editing |
| clean-user-facing-text | `clean_text.py`, `inspect_text.py`, `text_unicode.py`, `score_stylometry.py` | Final cleanup step plus a stylometry gauge |
| clarity-review | `frame_scan.py` | Repeated-frame detection |
| ehs-seo-blog-optimized | `metrics.py`, `mechanical_sweep.py`, `prose_signals.py`, `link_check.py`, `editorial_flow_check.py` | FKGL and word-count targets, sweep, link checks |
| sds-hero-stock | `reframe.py`, `check_photo.py`, `hero_compose.py`, `overlay.py` (`inner_logo.py`, `svgify.py` vendored for later) | House-style hero branding on generated images |

Prompts for the generation steps will be adapted from each skill's `SKILL.md` instructions and stored as versioned prompt templates in the admin.

## Hero image step (M6)

Follows the sds-hero-stock skill, with the photo generated instead of picked from stock:

1. **Prompt:** the `fast` profile writes an image prompt from the title and the article opening: the subject in the right third facing left, a calm, bright left half, correct PPE, no text.
2. **Photo:** the `image` profile generates it at 1440×816 (Cloudflare FLUX.2 klein by default, ComfyUI optional). The unbranded photo is saved as a Wagtail image.
3. **Vision check (skill step 2):** the `vision` profile (Gemini 3.7 Flash, falling back to local `qwen3-vl:8b-instruct`) returns the subject box, whether a person forms the subject's left edge, which way they face, any readable text or logos, and safety contradictions with the article (missing PPE and similar). Text and safety findings go into the version notes under "Problems to check". If the check fails, branding continues with the prompted layout and the note says nothing was checked.
4. **Reframe:** `reframe.py` puts the subject's left edge at 62% of the width. A right-facing photo is flipped only when it has no readable text and the subject stays on the right. If the left side needs a fill and the strip is at most 15% of the width, it's a mirrored fill (`--fill mirror`), which you accepted on 2026-10-13: the veil is at least 99.7% opaque there, so the copy can't show. Wider strips would need a generative fill, which isn't installed in the container (no LaMa). Then a 16:9 photo whose subject starts at 50% or further right is branded as it is with a note; otherwise one more photo is generated with a firmer placement instruction, and if that also fails the note asks you to regenerate.
5. **Check:** `check_photo.py` measures the fade strip and how calm the left side is; misses are listed as problems.
6. **Brand:** `hero_compose.py` adds the veil, glow, logo and the fitted headline. The headline is the selected title, marked up as the skill says: the topic term up to the colon in periwinkle and a line break after the colon (EU: grey lead, periwinkle second). The branded 1440×810 master is saved as a Wagtail image named after the visual copy.
7. **Headline too long** (the script's exit code 3): no branded image; the note shows the script's character budget. Regenerate with a note that starts with `Headline:` and a shorter version, e.g. `Headline: **SDS Retention:** | How Long to Keep Them`. A `Headline:` note re-brands the same photo without generating a new one.

The checks panel shows whether the hero is branded, the headline fit and contrast, the photo check, where the subject starts, and how many problems were found.

## Publish step (M7)

1. **Article:** the approved Final cleanup output (else Review and edit, else Draft). Leftover workflow sections (`## Changelog`, `## Metadata options`, `## Localisation notes`) are dropped.
2. **Page fields:** the article's H1 is the page title; the selected title option is the SEO title, the selected meta description the search description, and the selected slug the slug (made unique under Articles). The approved hero is the hero image. Primary keyword and region are stored on the page.
3. **Body:** Markdown becomes StreamField blocks: H2 and H3 are heading blocks, Markdown tables are table blocks, and everything between is rich text (bold, italic, links, lists, H4, quotes, code). Model output is sanitised first; scripts, images and unsafe links are dropped.
4. **Draft and moderation:** the page is saved as a draft revision under **Articles** (created under the home page on first use) and Wagtail's workflow for that part of the tree starts (the default **Moderators approval**). A moderator approves and publishes it in Wagtail. Running Publish again updates the same page with a new revision and doesn't restart a workflow already in progress.
5. **Warnings** in the version notes: claims still marked `[VERIFY]`, a missing meta description, no approved hero.
6. **Webhook (optional):** with `STUDIO_PUBLISH_WEBHOOK_URL` set, the worker POSTs JSON (`event: article.draft_saved`, run and page IDs, title, SEO title, slug, meta description, region, keywords, workflow, admin URL, warnings, and the Markdown export) after saving. With `STUDIO_WEBHOOK_SECRET`, the request carries `X-Studio-Signature: sha256=<HMAC-SHA256 of the body>`. A failed webhook is reported in the notes and doesn't fail the step.
7. **Exports** on the Publish step: Markdown with YAML front matter, a standalone HTML file, Word (metadata block, hero, headings, lists, tables, links), and the hero as the 720×405 WebP the CMS serves. If the Localise step is approved, the localised variant is exported too (Markdown, Word).

While the Publish step waits for review, **Run publish again** updates the page after you change the title, meta description or slug. Approving the Publish step finishes the run. The article page links back to the run in the page editor.

## Site crawl step (guest posts)

Runs after the brief for `outbound` content and mirrors the SITE_PROFILE in the `ehs-outbound-blog` skill. It reads the target site's landing page and at least three articles, preferring ones close to the topic, then summarises the dominant pattern. Rules:

- Public pages only; pages that need a login are never fetched.
- robots.txt is respected; pace is about one page every 5 seconds; at most 8 pages.
- Pages are fetched with the `Fetch Page` fallback chain (direct request with an honest user agent, then a reader service, then a scraping API). A page that still fails is skipped and listed, never forced.
- You can add a specific article URL to read, edit the profile, or re-crawl before approving.

## How steps run (M4)

- Starting a run, approving a step, regenerating and retrying all **queue** a step; the `worker` container runs it as a background task (`apps/studio/tasks.py`).
- Each step's prompt lives in `apps/studio/prompts/` and receives the brief plus the approved output of earlier steps (site profile → research → outline → draft → edited draft). A regenerate note is passed to the model for that attempt only.
- Model choice: the step's chosen model, else its profile default. If the call still fails after the provider retries, the profile's **fallback model** is tried once and the version notes say so. If that fails too, the step shows **Failed** with a plain-language reason and a **Retry** button.
- Steps without an approval gate (Final cleanup) continue automatically.
- When a step becomes ready, a message appears on your next admin page view, and the sidebar badge counts it. The run workspace refreshes itself while a step is queued or running, with elapsed time against the model's typical duration.
- **Research has no live web search yet.** The model works from what it knows and marks uncertain claims `[VERIFY]`; a search provider can be added later.
- Review and edit runs the seven-part sequence (`apps/quality/review.py`). Grades use the skill's own `metrics.py` formula. Every rewrite is checked before it's accepted (headings kept, no large loss of text); a rejected rewrite leaves the text unchanged and says why. Sentence splits are **proposals only**: each must lower its section by at least one grade, and you apply the ones you tick.
- Final cleanup runs the clean-user-facing-text `clean_text.py` script (built-in cleaner as fallback).
- Drafts, edits, cleanups and localisations get **quality scans** from the vendored skill scripts (slop index, AI-tell findings, unclear references, repeated frames, mechanical-sweep blockers, hidden characters), shown in the run workspace.
- Publish saves the article as a Wagtail page draft and starts moderation ([below](#publish-step-m7)).

