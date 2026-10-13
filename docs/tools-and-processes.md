# Tools and processes

Everything we use to produce content with the Content Workflow Studio, and how the work flows. Detailed guides:

- [User guide](user-guide.md): writers, editors and moderators.
- [Operations guide](operations.md): running and maintaining the studio.
- [Development guide](development.md): developers and AI coding agents.
- [Deployment](deployment.md): sharing the studio over ngrok, and scaling it.

## Tools

### The studio

| Tool | What it's for |
|---|---|
| **Content Workflow Studio** | Runs the content pipeline (brief → research → outline → draft → review and edit → cleanup → hero → localise → publish) with an approval gate after each step. Lives in the Wagtail admin under **Content Studio** |
| **Wagtail 8 (Django 6.1)** | The admin, page tree, image library, revisions and the **Moderators approval** workflow that publishes articles |
| **Postgres 17** | All content, run history and the background task queue |
| **Docker Desktop** | Runs the web, worker, database and migrate containers on the Windows host |
| **Caddy** and **ngrok** | Share mode: Caddy serves images and balances web containers; ngrok publishes it over HTTPS ([deployment.md](deployment.md)) |

### Content skills (Claude Code)

The studio automates the workflow these skills define. Their deterministic scripts are copied unchanged into the studio and run as quality checks.

| Skill | Used for | Scripts the studio runs |
|---|---|---|
| `ehs-seo-blog-optimized` | Articles for sdsmanager.com: research, outline, draft, edit, scoring | `metrics.py` (grades), `mechanical_sweep.py`, `prose_signals.py` |
| `ehs-outbound-blog` | Guest posts and bylines for other sites, including the site profile | (prompts only) |
| `deslop` | Removing AI-tell patterns | `lexical_scan.py`, `structure_scan.py`, `redundancy_scan.py` |
| `clarity-review` | Unclear references, repeated sentence frames, jargon | `frame_scan.py` |
| `clean-user-facing-text` | Hidden-Unicode removal before publishing | `clean_text.py`, `inspect_text.py` |
| `sds-hero-stock` | SDS Manager hero images in the house style | `reframe.py`, `check_photo.py`, `hero_compose.py`, `overlay.py` |

### AI models and providers (all free)

| Provider | Role | Default use |
|---|---|---|
| **Ollama on the host** | Local, private models (Qwen3.8 27B, GLM 4.7 Flash, Qwen3-VL) | Outline and draft (`quality`), vision fallback |
| **Ollama Cloud** (free plan) | Large open models (gpt-oss 120B, Nemotron 3, Gemma 4) | Research, hero prompts, review and edit (`fast`, `edit`) |
| **Groq** (free tier) | Very fast mid-size models | Fallback for `fast` and `edit` |
| **Gemini** (free tier) | Gemini 3.7/3.8 Flash | Hero vision check |
| **Cloudflare Workers AI** | FLUX.2 klein 4B, FLUX.1 schnell (Apache-2.0) | Hero photos |
| **ComfyUI on the host** | Local image generation (optional) | Hero photos when chosen |

Defaults are **interim** until the blind model evaluation is scored ([model-eval.md](model-eval.md)). Limits and terms: [providers.md](providers.md).

### Integrations and engineering tools

| Tool | What it's for |
|---|---|
| **n8n** (optional) | Receives each saved article draft through the publish webhook, for onward automation |
| **GitHub** + **GitHub Actions** | Source (public repository) and CI: lint, tests against Postgres, migration check, image build |
| **pytest**, **ruff** | Tests and lint/format, run inside the containers |
| **Claude Code** | AI pair-programming; follows [AGENTS.md](../AGENTS.md) and picks up work from [HANDOFF.md](HANDOFF.md) |

## Processes

### 1. Content production

| Stage | Who | What happens | Done when |
|---|---|---|---|
| Brief | Writer or editor | Fill in the brief (topic, keywords, region, grade, audience), choose steps and models, start the run | Run started |
| Site crawl (guest posts) | Writer | Check the target site's profile | Profile approved |
| Research | Writer | Check the claims; every `[VERIFY]` gets confirmed or removed | Research approved |
| Outline | Writer or editor | Shape structure and headings | Outline approved |
| Draft | Writer | Read the draft; choose title, meta description and slug | Draft approved, metadata selected |
| Review and edit | Editor | Check the grade table and changes; apply split proposals worth taking | Edit approved |
| Final cleanup | Automatic | Hidden characters removed, mechanical sweep | Automatic |
| Hero image | Editor | Check safety, readable text, headline fit; regenerate or re-brand as needed | Hero approved |
| Localise (optional) | Regional editor | Check regulations, spelling and units for the target region | Variant approved |
| Publish | Editor | Page draft created in moderation; check warnings; download exports if needed | Publish step approved |
| Moderation | Moderator | Final review in Wagtail; approving publishes the page | Page live |

Rules that apply throughout: you approve every step; no confidential material in briefs; resolve every `[VERIFY]` before publishing; safety-photo contradictions are fixed, not accepted.

### 2. Choosing models

1. Add candidates to `eval/candidates.yaml` (free, verified).
2. Run the evaluation round on the real briefs (`eval_models`).
3. Score the outputs **blind** in `scorecard.md`, then reveal with `eval_report`.
4. Set the winners as the profile defaults, record the evidence in [model-eval.md](model-eval.md).

Rounds: outline (complete, waiting for scores), draft, image and edit.

### 3. Checking providers

Use **Models and providers › Re-check providers** (or `ai_smoke`) after changing keys, when steps fail with provider errors, and before relying on a newly added model. Paid or unavailable models stay listed but disabled, with the reason.

### 4. Changing the studio

Plan against the [roadmap](roadmap.md) → build with tests and docs → check locally (lint, format, tests, migrations) → commit to `main` → CI green → update [HANDOFF.md](HANDOFF.md). Significant decisions become ADRs. Details: [development.md](development.md#change-and-release-process).

### 5. Keeping it running

Start Docker Desktop and Ollama, `docker compose up -d`, check the dashboard's Services panel. Back up the database **and** the media volume. Restart the worker after code or prompt changes. Re-copy skill scripts unchanged when the skills change. Details: [operations.md](operations.md).

### 6. Session handoff

Every working session (person or AI agent) ends by updating [HANDOFF.md](HANDOFF.md): state per milestone, what to do next, decisions waiting on someone, and gotchas learned. The next session starts by reading it.

## Roles

| Role | Responsibilities |
|---|---|
| Writer | Briefs, research checks, outlines, drafts, metadata choices |
| Editor | Review and edit, hero approval, publish step, exports |
| Moderator | Final approval in Wagtail's workflow; the only role that puts pages live |
| Operator | Stack, keys, providers, backups, updates |
| Developer / AI agent | Code, tests, docs, CI, handoff |

One person can hold several roles. Wagtail groups and permissions per role are part of M8.

## Current limits

- Research has no live web search; claims depend on model knowledge and your checks.
- No generative fill for heroes in the container: narrow strips use a mirrored fill under the opaque veil; wider gaps need a regenerated photo.
- Localised variants are exports, not separate pages.
- Model defaults are interim until the evaluation is scored.
- Roles, automated backups and a production deployment are M8.
