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
| SITE, SITE_DOMAIN, NARRATIVE_MODE | Outbound pieces only: target site and its voice |

## Pipeline steps

| # | Step | Output | Gate | Default profile |
|---|---|---|---|---|
| 0 | Accuracy gate (optional) | Findings: apply-now vs confirm-first | Approve | quality |
| 1 | Research | Sources, claims, verification table | Approve | fast |
| 2 | Outline | Detailed outline + headings-only outline + structure decisions | Approve (edit allowed) | quality |
| 3 | Draft | Full draft, three metadata options per field, link map | Approve (optionally per H2) | quality |
| 4 | Edit and de-AI | Revised article plus changelog, with quality-check results | Approve | quality |
| 5 | Final cleanup | Hidden-Unicode removal, final mechanical sweep | Auto | none (deterministic) |
| 6 | Hero image | Generated image plus branded hero (WebP/PNG) | Approve | image |
| 7 | Localise (optional) | Regional or language variants | Approve | quality |
| 8 | Publish | `ArticlePage` draft → Wagtail moderation workflow | Wagtail workflow | none |

**Profiles** map to a provider and model in configuration (see [providers.md](providers.md)):

- `quality`: slower, best writing
- `fast`: quick extraction and summaries
- `image`: hero image generation

## Approval actions

On each step awaiting approval you can:

- **Approve:** accept the output and queue the next step.
- **Edit & approve:** change the output in the admin editor, then continue. Your edited version is what later steps see.
- **Regenerate:** rerun the step, optionally with a different provider or model.
- **Reject:** stop the run and record why.

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
