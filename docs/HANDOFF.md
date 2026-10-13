# Handoff: Content Workflow Studio (state on 2026-10-13, M6 built)

Read this first in a new session. Also see `docs/roadmap.md`, `docs/workflow.md`, `docs/ux.md`,
`docs/providers.md`, `docs/model-eval.md` and `AGENTS.md`.

## Start here

1. Score the outline evaluation (below), then set the default models.
2. Optional: install ComfyUI and export the workflow (`docs/setup.md` step 6) to test local hero images live.
3. Then M7 (publish) and M8 (hardening) per `docs/roadmap.md`.

## Where things stand

| Milestone | State | Commit |
|---|---|---|
| M1 Bootstrap (Wagtail 8 / Django 6.1, Docker: web, worker, db, migrate; CI) | Done | 4731851 … c6786ca |
| M2 AI provider layer + blind model evaluation | Built; **outline round complete (36/36), waiting for your blind scores** | c9e65a6 |
| M3a UX (wireframes: https://claude.ai/artifact/GjFjc7himFSZiHNYkKV9tw, copy in `docs/wireframes/`) | Done | 51ab651, 2c47c69 |
| M3b Content Studio screens in the Wagtail admin | Done | c84881e |
| M4 Background generation (worker runs steps, fallback, retry, notifications) | Done, verified live (run 9) | 67641ab |
| M5 Seven-part review-and-edit sequence + vendored skill scripts | Done, verified live (run 10) | 5df13ae |
| M6 Images (ComfyUI provider, vision check, sds-hero-stock branding) | Built, verified live on run 9 (Cloudflare + Gemini vision + branding); ComfyUI mocked | see git log |
| M7 Publish (ArticlePage, moderation, exports, n8n hook) | Planned | – |
| M8 Hardening | Planned | – |

M1–M5 are pushed to `main` on GitHub (CI runs on every push). Check `git status` for M6.

## Evaluation (M2)

- Run folder: `eval/runs/r1-outline/` (git-ignored). **All 36 outlines are done (12 models × 3 briefs).**
- Reasoning settings, which matter when you interpret scores:
    - Qwen3.8 27B: reasoning on, all briefs.
    - glm-4.7-flash: reasoning off, all briefs (on, it returned empty output).
    - Qwythos 9B: reasoning off for `b1-sds-retention` only; the other two briefs ran with the model's default (on) before the empty output appeared. `eval/candidates.yaml` now has it off.
    - Ornith 9B: model default.
- Run long evals in a **one-off container**:
  `docker compose run --rm --no-deps -T web python manage.py eval_models --round outline --run-dir eval/runs/r1-outline`
  (an `exec` into `web` dies if the dev server reloads on a code error).
- Then score `eval/runs/r1-outline/scorecard.md` blind (open `key.json` only after), run `python manage.py eval_report eval/runs/r1-outline`, pick defaults, set `AI_PROFILES` in `config/settings/base.py` and `AI_PROFILES_INTERIM = False`.
- Later rounds: draft (best outline per brief in `eval/outlines/`), image, and edit (one draft per brief in `eval/drafts/`).

Verified free models: local Ollama (Qwen3.8 27B ~19 min/outline at 4.5 tok/s; glm-4.7-flash with think off; Ornith 35B-A3B; Ornith 9B; Qwythos 9B), Ollama Cloud free (nemotron-3-ultra/super, gpt-oss:120b, gemma4:31b), Gemini free (3.8/3.7 Flash; Pro has no free quota; 2.5 closed), Groq (gpt-oss-120b; qwen3.8-27b limited to 1,000 output tokens/min), Cloudflare images (flux-2-klein-4b, flux-1-schnell). NVIDIA NIM, Mistral and OpenRouter are not usable.

## M6 notes

- How the hero step works: `docs/workflow.md#hero-image-step-m6`. Code: `apps/studio/executors.py` (`hero_image`), `apps/quality/hero.py`, `apps/ai/images/comfyui.py`.
- Brand assets are git-ignored (ADR 0004). A fresh clone needs `docs/setup.md` step 5, or heroes come out unbranded with a note.
- No generative fill in the container (LaMa needs PyTorch). Strips up to 15% of the width get the skill's mirror fill (you accepted it on 2026-10-13; the veil is fully opaque there). Beyond that, a subject starting at 50% or more is branded as it is; further left, one more photo is generated, then you're asked to regenerate. FLUX tends to centre the subject (48–57% in the live runs).
- A `Headline:` regenerate note re-brands the same photo (no new image); used live to fix a too-wide subject box.
- Gemini 3.7 Flash returned HTTP 500 for several image requests; the Qwen3-VL 8B fallback worked but boxes subjects less tightly (it included furniture until the prompt excluded it).
- gpt-oss spends its token budget on reasoning: the hero prompt step needed `max_tokens` 3000 (600 returned empty text, and an empty prompt now fails the step).

## Gotchas learned

- Django 6.1 needs `django.contrib.postgres` in `INSTALLED_APPS` (Wagtail search on Postgres).
- pytest must use `--ds=config.settings.test` (containers set `DJANGO_SETTINGS_MODULE`); test settings use DummyCache, `STUDIO_EXECUTE_STEPS=False`, `STUDIO_QUALITY_SCANS=False`.
- The openai SDK 3.x bundles `httpx2`; tests inject a mock transport through `openai_compat.http_client_factory`.
- Groq rejects Python's default User-Agent (403); every request sends `AI_USER_AGENT`.
- Wagtail's `--w-color-*-50` tints don't switch in dark mode; the studio CSS mixes tints from foreground colours.
- Selects size to their longest option; panel controls are constrained to 100% width.
- Vendored skill scripts are excluded from ruff and must stay byte-identical (re-copy from `~/.claude/skills` to update).
- The `worker` container (db_worker) does not reload code or cached prompt templates: `docker compose restart worker` after changing executors or prompts.
- Docker Desktop must be started manually (`D:\Docker\Docker Desktop.exe`). Your admin user is `sdsmanager`.
