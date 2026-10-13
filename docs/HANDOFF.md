# Handoff: Content Workflow Studio (state on 2026-10-13)

Read this first in a new session. Also see `docs/roadmap.md`, `docs/workflow.md`, `docs/ux.md`,
`docs/providers.md`, `docs/model-eval.md` and `AGENTS.md`.

## Where things stand

| Milestone | State | Commit |
|---|---|---|
| M1 Bootstrap (Wagtail 8 / Django 6.1, Docker: web, worker, db, migrate; CI) | Done, **pushed** | 4731851 … c6786ca |
| M2 AI provider layer + blind model evaluation | Built; **outline round complete (36/36), waiting for your blind scores** | c9e65a6 |
| M3a UX (wireframes: https://claude.ai/artifact/GjFjc7himFSZiHNYkKV9tw, copy in `docs/wireframes/`) | Done | 51ab651, 2c47c69 |
| M3b Content Studio screens in the Wagtail admin | Done | c84881e |
| M4 Background generation (worker runs steps, fallback, retry, notifications) | Done, verified live (run 9) | 67641ab |
| M5 Seven-part review-and-edit sequence + vendored skill scripts | Done, verified live (run 10) | 5df13ae |
| M6 Images (ComfyUI + sds-hero-stock branding) | **Started, not committed** | – |
| M7 Publish (ArticlePage, moderation, exports, n8n hook) | Planned | – |
| M8 Hardening | Planned | – |

**Commits c9e65a6 → 5df13ae are LOCAL ONLY.** You asked not to push until you'd seen the evaluation outputs. Push with `git push origin main` when ready (CI runs on push).

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

## M6 in progress (pick up here)

Done so far:
- Vendored the sds-hero-stock scripts and assets **unchanged** into `apps/quality/vendor/sds_hero_stock/` (uncommitted).
  **Decision needed:** the assets include the SDS Manager logo, and the repo is public. Decide whether to commit them, keep them out of git, or make the repo private.
- Resolved dependencies for the container: `numpy==2.5.4`, `scipy==1.18.1`, `fonttools==4.66.1` (Pillow 12.3.0 already present). Not yet added to `requirements.txt`.

Planned design (agreed direction):
1. Hero image prompt asks for the subject in the right third and a calm left side, 16:9; generate at about 1440×816.
2. A **vision** profile (Gemini 3.7 Flash; fallback local `qwen3-vl:8b-instruct`) returns the subject box, person-at-fade, readable text/logos, and safety contradictions (missing PPE etc.), reported in the version notes as the skill requires. The Ollama native adapter must convert list-style message content into `images: [base64]`.
3. Branding with the vendored scripts: `reframe.py` (subject box; fill `auto` falls back without LaMa, so report "regenerate with the subject further right") → `check_photo.py` → `hero_compose.py` (headline markup from the selected title: `**topic up to colon:** | rest`). Exit code 3 = headline too long: show the skill's message; a regenerate note starting `Headline:` overrides the headline.
4. Store the raw and the branded image as Wagtail Images; version metrics get a `hero` block (check numbers, headline fit, flags).
5. ComfyUI provider (`apps/ai/images/comfyui.py`): POST `/prompt` with the user's exported API-format workflow (patch prompt text, latent width/height and seed by node class), poll `/history/{id}`, fetch `/view`; unload Ollama models (`keep_alive: 0`) before, POST `/free` after. Add a catalog entry and docs on exporting the workflow. ComfyUI itself isn't installed yet (large download; user approves).
6. Tests: mocked ComfyUI and vision; run the real vendored branding scripts on a synthetic 1440×810 image.

## Gotchas learned

- Django 6.1 needs `django.contrib.postgres` in `INSTALLED_APPS` (Wagtail search on Postgres).
- pytest must use `--ds=config.settings.test` (containers set `DJANGO_SETTINGS_MODULE`); test settings use DummyCache, `STUDIO_EXECUTE_STEPS=False`, `STUDIO_QUALITY_SCANS=False`.
- The openai SDK 3.x bundles `httpx2`; tests inject a mock transport through `openai_compat.http_client_factory`.
- Groq rejects Python's default User-Agent (403); every request sends `AI_USER_AGENT`.
- Wagtail's `--w-color-*-50` tints don't switch in dark mode; the studio CSS mixes tints from foreground colours.
- Selects size to their longest option; panel controls are constrained to 100% width.
- Vendored skill scripts are excluded from ruff and must stay byte-identical (re-copy from `~/.claude/skills` to update).
- Docker Desktop must be started manually (`D:\Docker\Docker Desktop.exe`). Your admin user is `sdsmanager`.
