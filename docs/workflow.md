# Content workflow

The studio automates an existing, proven manual workflow that runs as a set of Claude Code skills (`ehs-seo-blog-optimized`, `ehs-outbound-blog`, `deslop`, `clarity-review`, `clean-user-facing-text`, `sds-hero-stock`). The app keeps its structure: **each phase produces an artefact, and you approve it before the next phase starts.**

## Brief (inputs)

| Field | Meaning |
|---|---|
| Type | `seo_blog` (for sdsmanager.com), `outbound` (guest post), `pillar`, `lead_magnet`, `whitepaper` |
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
| 0 | Accuracy gate (optional) | Findings: apply-now vs confirm-first | Approve | quality |
| 0b | Site crawl (guest posts only) | Site profile: narrative mode, voice, heading style, typical length, reading level, link habits; list of pages read or skipped | Approve (edit allowed) | none (fetching) + fast (summarising) |
| 1 | Research | Sources, claims, verification table | Approve | fast |
| 2 | Outline | Detailed outline + headings-only outline + structure decisions | Approve (edit allowed) | quality |
| 3 | Draft | Full draft, three metadata options per field, link map | Approve (optionally per H2) | quality |
| 4 | Review and edit | Revised article plus a per-section changelog and grade report ([sequence below](#review-and-edit-step-m5)) | Approve | edit |
| 5 | Final cleanup | Hidden-Unicode removal, final mechanical sweep | Auto | none (deterministic) |
| 6 | Hero image | Generated image plus branded hero (WebP/PNG) | Approve | image |
| 7 | Localise (optional) | Regional or language variants | Approve | quality |
| 8 | Publish | `ArticlePage` draft → Wagtail moderation workflow | Wagtail workflow | none |

**Profiles** map to a provider and model in configuration (see [providers.md](providers.md)):

- `quality`: slower, best writing
- `fast`: quick extraction and summaries
- `edit`: targeted revision in the review-and-edit step (may differ from the drafting model)
- `image`: hero image generation

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
| sds-hero-stock | `hero_compose.py`, `overlay.py`, `reframe.py`, `inner_logo.py` | House-style hero branding on generated images |

Prompts for the generation steps will be adapted from each skill's `SKILL.md` instructions and stored as versioned prompt templates in the admin.

## Site crawl step (guest posts)

Runs after the brief for `outbound` content and mirrors the SITE_PROFILE in the `ehs-outbound-blog` skill. It reads the target site's landing page and at least three articles, preferring ones close to the topic, then summarises the dominant pattern. Rules:

- Public pages only; pages that need a login are never fetched.
- robots.txt is respected; pace is about one page every 5 seconds; at most 8 pages.
- Pages are fetched with the `Fetch Page` fallback chain (direct request with an honest user agent, then a reader service, then a scraping API). A page that still fails is skipped and listed, never forced.
- You can add a specific article URL to read, edit the profile, or re-crawl before approving.

