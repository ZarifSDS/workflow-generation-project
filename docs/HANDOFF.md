# Handoff: Content Workflow Studio (state on 2026-10-14 night: pipeline aligned with the ehs-seo-blog-optimized skill)

Read this first in a new session. Then `docs/development.md` (code map, how-tos, process) and `docs/tools-and-processes.md`. Also see `docs/roadmap.md`, `docs/workflow.md`, `docs/ui-ux-plan.md`, `docs/security.md`, `docs/providers.md`, `docs/model-eval.md` and `AGENTS.md`.

## Where we are

**Everything is committed and pushed** (see `git log`; the last commits are fa78bbe "Company CMS page types and default models per task" and the "Skill-aligned pipeline" commit after it). Tests: 303 passed; frontend 40 passed; ruff clean. Share mode is running, rebuilt with the latest code (`--build`, 2 web + 2 worker). No step is queued or running.

The user's direction:
- A fast, functional, visually better version of the current Wagtail CMS with better UX. No rebranding.
- The page types replicate the company CMS (https://cms.sdsmanager.com/admin/, Wagtail 6.3, headless) 1:1, improved where we judge it better. Inspect it through Claude in Chrome in the user's Brave (logged in; read only, never save there) instead of asking for screenshots. JavaScript that returns hrefs/query strings is blocked there; use get_page_text and find.
- The pipeline follows the user's `ehs-seo-blog-optimized` skill (`~/.claude/skills/ehs-seo-blog-optimized/`) for research, outline and draft. Its Step 3 is NOT used: Review and edit = scan, then a /deslop rewrite, then a /clarity-review rewrite, then grade tuning.
- Final goal: once tuned, one-shot generation of the whole pipeline. For now, smooth the step-by-step workflow.
- The user asks before each commit and push.

### The pipeline now (what each step does)

| Step | What happens | Code |
|---|---|---|
| Search results (first, optional, automatic) | Top 10 results for the brief's locale from the first configured provider (Serper, Brave, Google Programmable Search, then keyless **DuckDuckGo** as the default, then Ollama web search with the Ollama Cloud key); Google autocomplete (keyless); reads the top pages politely and measures H1–H3 outline, title tag, date, words, FKGL, FAQ, tables, video, forms, question H2s | `apps/studio/serp.py`, keys under **Settings › Search data providers** |
| Research | Skill Step 1: Search Intent, What Ranks, **Must Include**, **Missing Opportunity** (no "Do better", by the user's choice), Keyword Table, Questions, Sources by tier, Claims with status, Misconceptions, **Cannibalization** against the vendored internal article index | `prompts/research.md`, `apps/studio/houseref.py` |
| Outline | H1 options, format + length vs the ranking median, H2s as real queries, H3 necessity test, ~30% rule, per-section words, capsules, Intro/Conclusion/FAQ plans (product from the vendored registry), claim table, structure decisions with alternatives, headings-only outline (Key Takeaways first, FAQ last). Article headings are written as `H2:` lines so the plan isn't graded as an article | `prompts/outline.md` |
| Draft | Skill Step 2 + component specs: sees the research; intro with the literal "this article" scope sentence, Key Takeaways, core in the first H2, capsules, `[SRC: url]`, `[VISUAL: …]`, verb-first CTA conclusion with one registry product (+ button label when CTA style is button), FAQ (`:::faq`), References; house style (no dashes, straight quotes, Title Case); metadata with 3 options each for Meta Title, Meta Description, Slug, **Tags**, **Excerpt** | `prompts/draft.md`, `prompts/_rules.md`, `textclean.split_metadata` |
| Review and edit | Scan (deslop lexical with the skill's banned-word TSV and Title Case allowed, structure, redundancy; clarity frame scan with the keywords as terms; whole-article metrics) → **deslop rewrite** → **clarity-review rewrite** → **grade tuning** per H2 (H3s in sections over 300 words), more than 1 above target, hardest first, max 10, by syntactic unpacking → re-scan + report (slop index, FKGL before/after, clarity edits, substantive questions for the author) | `apps/quality/review.py`, `prompts/review_{deslop,clarity,wordlevel}.md` |
| Final cleanup | clean-user-facing-text, then house-style mechanics (dashes, curly quotes, emoji, thematic breaks, escaped punctuation, spacing, `[HERO:]` cues), then the mechanical sweep. If `[VERIFY]`, `[SRC:]` or `[VISUAL:]` remain it **holds for review** and can't be approved; "Strip [SRC:] markers" helper | `apps/quality/house.py`, `executors.cleanup`, `services.strip_sources` |
| Publish | Refuses while markers remain. Excerpt → page Intro, chosen Tags → page tags; a quoted button label after the product link becomes a **CTA button block** | `executors.publish`, `apps/content/publishing.py`, `markup.build_article` |

Every rewrite (edit step, chat apply, Tune) passes `review.accept_rewrite`: headings kept, most words kept, **protected spans** (numbers with their unit, section/regulation refs, URLs, acronyms, markers) unchanged and **no negation lost** (unfolding "not X but Y" is allowed). Tune also refuses a drop over 1.5 grades that leaves sentences flat (≥ 70% in one length band, judged on ≥ 4 sentences).

### Also built this session

- Company CMS page types (fa78bbe), Settings › Default models per task, AI providers page.
- Steps can't start before their input is approved (model choice/Retry on a waiting step keeps it pending; approving the previous step starts it or restarts a failed next step).
- Timers: server-rendered elapsed (right on reload), live times in the step list, time in queue, "took" per step/version, slow-step warning.
- Audience profiles per region (Settings › Audience profiles; seeded B2B SaaS EHS, grade 8), fed to every prompt and the chat; the wizard pre-fills per region.
- Reading grade only on article steps (draft, review and edit, cleanup, localise): whole-article FKGL + sentence-length spread, then per-section rows (references, tables, notes not graded).
- Suggestions chat + Tune buttons on steps waiting for review (`apps/studio/assistant.py`, worker task `run_chat`); models in Settings › Default models (Suggestions chat, Section tuning).
- Send back with feedback (regenerate with a chosen model, or targeted edits through the chat); Reject the whole run; Reopen a rejected run (optionally regenerating with the reason).
- Logo on in-article images: editor uploads get the SDS Manager logo by `sds-hero-stock`'s `inner_logo.py` (corner and regular/negative version chosen to avoid clashes), with a **Logo position** choice (Automatic, top/bottom left/right) and an opt-out. Images chosen from the library aren't re-branded.
- Site-mapping eval (`tests/test_site_mapping.py`): a skill-style article renders every component; pages created directly under Root (as in the headless company CMS) have no public URL here, so listings and language links now skip them instead of printing `href="None"`.

### Things a new session must know

- Develop while share mode runs with one-off dev containers: `docker compose run --rm --no-deps -T web …` (bind-mounted code); share mode bakes the image, so `--build` it after changes.
- **Never write Python with backslashes through Bash heredocs** in this environment: `\n` turns into a real newline (it broke files several times on 2026-10-14). Write scripts with the Write tool into the scratchpad and run them with `python -I`.
- Tests switch the Search results step off by default (`tests/conftest.py`); mark a test `search_step` to keep it.
- Vendored skill files are byte-identical copies, except `internal-article-links.md`, which keeps only published rows (`apps/quality/vendor/README.md`); added on 2026-10-14: `ehs_seo_blog/data/{banned-words.tsv,internal-article-links.md,product-link-registry.json}` (lead-magnet-links.md is deliberately not vendored: it lists unreleased items from an internal tracker and the repo is public).
- `STUDIO_SECRETS_KEY` is in `.env`; back up `.env` separately.

### Ideas the user raised, not built yet

- Turn the combined workflow knowledge into an agent with an SOP that adapts to whichever model is used (a single model-agnostic SOP document behind every step), as the path to one-shot generation.
- Sectional drafting (approve one H2 at a time), link_check / editorial_flow_check scripts from the skill, re-branding images chosen from the library.
- Run 12 ("management of change safety") is rejected; it can be reopened from its banner.

## What was built on 2026-10-13/14 (after M8)

| Commit | What | Where to read |
|---|---|---|
| 2fef876 | **SVG and WebP images**: SVG added to `WAGTAILIMAGES_EXTENSIONS`, served with a sandboxing CSP (`SvgSandboxMiddleware`, Caddy), rasterised by CairoSVG for DOCX | `docs/operations.md`, `tests/test_image_formats.py` |
| 45ee088 | **M9 phase 4**: Tiptap 3.31.3 editor in `frontend/` (vanilla JS, esbuild), Edit → Save as new version / Save and approve, Visual/Markdown, browser autosave + restore, `base_version` conflict check | `docs/ui-ux-plan.md` › Phase 4 |
| a097fa2 | **Provider keys in the admin** (ADR 0008): Settings › AI providers (superusers): set/replace/remove keys, add OpenAI-compatible providers (OpenRouter) and models; Fernet under `STUDIO_SECRETS_KEY` from `.env`; write-only, last-4 hint, history entries; `rotate_provider_keys` | `docs/security.md` › Provider keys, `docs/adr/0008-*` |
| bdf7c79 | **M9 phase 5**: Wagtail page/document/image choosers in the editor, upload by button/drag/paste (alt required), YouTube/Vimeo embeds (`WAGTAILEMBEDS_FINDERS`), `/` menu, writers get image/document add+choose | `docs/ui-ux-plan.md` › Phase 5 |
| 12d43c6 | **M9 phase 6**: word-level and rendered Compare, link tooltips and shortcut list in the editor, studio templates without inline styles, public article CSS for figures/embeds/FAQ/tags, draft-prompt FAQ aligned with the blog skill, end-to-end check through Publish | `docs/ui-ux-plan.md` › Phase 6 |

The Content Studio Handbook artifact (https://claude.ai/artifact/Cp91uDDbGKT2H2qqPa8Cn4, private) was updated on 2026-10-14 to match.

### Things a new session must know

- **`STUDIO_SECRETS_KEY` is in `.env`** (generated 2026-10-14). It encrypts admin-stored provider keys; database backups don't contain it. Back up `.env` separately. No keys are stored in the admin yet; all providers still use `.env`.
- **Share mode needs `--build` once**: the images changed (Node stage for the editor bundle, `libcairo2`, `cairosvg`, `cryptography`). Dev was rebuilt already.
- **Dev has a `frontend` service** (`npm ci && npm run watch`, node_modules in a named volume) that rebuilds `apps/studio/static/studio/editor/` (git-ignored) on changes. By hand: `cd frontend && npm run build`; tests: `npm test`.
- **Restart the worker after prompt changes**; the draft prompt changed on 2026-10-14 (done then).
- Built-in browser pane limits (for testing the editor): no animation frames, `<dialog>` close events don't fire, screenshots miss the dialog top layer, synthetic double-clicks don't select words. Check behaviour through the DOM (`form.studioEditor` is the editor instance).

## Restarting after the PC was off

Nothing needs to be re-generated: no step was queued or running at shutdown, and runs resume where they stopped. Data is in the Docker volumes on `D:\DockerData`.

0. `cd D:\workflow-generation-project` first: compose looks for its files in the current folder.
1. Start Docker Desktop (`D:\Docker\Docker Desktop.exe`) and wait for "Engine running".
2. Start Ollama from the Start menu (needed for the local `quality` models: outline, draft).
3. Start the studio in one mode (the dev image is built; **share mode needs `--build` once** after the 2026-10-14 changes, then only after code changes):
   - Shared over ngrok: `docker compose -f docker-compose.yml -f docker-compose.share.yml up -d --scale web=2 --scale worker=2`. The public URL is the same (`docker compose -f docker-compose.yml -f docker-compose.share.yml logs ngrok`).
   - Dev only: `docker compose up -d` (http://localhost:8000/admin/).
4. Check: `docker compose ps` (add the same `-f` files in share mode) shows db healthy, web healthy, worker and backup running; the dashboard's Services panel shows Ollama reachable. The `backup` service takes a backup on start.

Waiting for review (4 steps, unchanged since 2026-10-13; throwaway test runs 13–16 and page 6 were deleted): run 11 Research and run 12 Outline ("management of change safety"), run 10 Review and edit, run 9 Publish ([Live test]). The `[Example]` demo runs 5–8 were deleted on 2026-10-13 (briefs kept; backup `backups/db-20261013-120342.dump` taken just before).

## Start here

1. Score the outline evaluation (below), then set the default models.
2. Optional: install ComfyUI and export the workflow (`docs/setup.md` step 6) to test local hero images live.
3. Review run 9's article (page 5) before a moderator approves it: two claims are still marked [VERIFY], and its meta description says "30 days after last use federally" (OSHA's records rule talks about 30 years).
4. Put teammates into the four groups (Writers, Editors, Moderators, Operators) under Settings › Users.
5. Try the editor on a real step (Edit on run 11's Research or run 12's Outline) and say what to polish; optionally add an OpenRouter key and models under Settings › AI providers.
6. Copy `backups/` (and `.env`, separately) off the PC now and then; `D:\backups\docker-2026-10-13\` (manual backups from the disk-full incident) can be deleted once everything is confirmed working.
7. Optional: point the publish webhook at an n8n workflow (`docs/setup.md` step 7); move to a server with `docker-compose.prod.yml` when ready (`docs/deployment.md`).

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
| M7 Publish (ArticlePage, moderation, exports, n8n hook) | Built, verified live on run 9 (draft page 5 in Moderators approval; MD/HTML/DOCX/WebP exports); webhook mocked | see git log |
| M8 Hardening (roles, login protection, secret review, backups, production compose) | Built; see `docs/security.md` | see git log |

| SVG/WebP images | Done | 2fef876 |
| M9 UI/UX overhaul (dialect, article page, theme, editor, choosers, compare) | Done, verified end to end | eb5778d, 45ee088, bdf7c79, 12d43c6 |
| Provider keys in the admin (ADR 0008) | Done | a097fa2 |

Everything is pushed to `main`; CI (lint and tests, frontend, image build, secret scan) is green at 12d43c6.

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

## M7 notes

- How publishing works: `docs/workflow.md#publish-step-m7`. Code: `apps/content/` (`models.py`, `markup.py`, `publishing.py`, `exports.py`), the `publish` executor, and `run_export` in `apps/studio/views/runs.py`.
- Run 9's article is page 5 (`/home/articles/...`), a draft waiting in Moderators approval. Its text still has two `[VERIFY]` claims, and the meta description says "30 days after last use federally", which looks wrong (OSHA's records rule talks about 30 years). Check it before approving.
- Steps without a model (Final cleanup, Publish) have a **Run again** button while they wait for review. Once approved, a step can only be rerun from code (`status = queued` + `services.enqueue`).
- Localised variants are exports only; no second page is created (Wagtail i18n isn't enabled).

## Share mode (2026-10-13)

- `docker-compose.share.yml` + `deploy/Caddyfile`: production mode behind Caddy and an ngrok tunnel; `--scale web=N --scale worker=N` works. Details: `docs/deployment.md`, ADR 0005.
- Verified: the public URL (the ngrok account's free dev domain; see `docker compose logs ngrok`, not recorded here because the repo is public) serves admin, static and media through 2 web + 2 worker containers; login CSRF passes; `DEBUG` off.
- The ngrok authtoken is reused from the Windows (Store) ngrok agent config via `NGROK_CONFIG_FILE` in `.env`; it's never copied anywhere.
- Docker's disk moved to `D:\DockerData` after C: filled up and Docker kept trying to reformat its disk (see operations.md › Disk space). Backups from that day: `D:\backups\docker-2026-10-13\` (SQL dump, media archive, every volume).

## M8 notes

- Roles: `apps/studio/permissions.py`, groups from migration `studio.0004_m8_groups`; enforced in views and `permissions.can_act`. Superusers bypass.
- Login lockout: django-axes 8.3.1 (declares Django 6.0 support; tested on 6.1). Unlock with `axes_reset_username`.
- Secrets: `apps/ai/redact.py` runs on every `ProviderError`, failed-step error and log line. CI job `secret-scan` runs gitleaks over the full history.
- Backups: `backup` service in `docker-compose.yml` (`deploy/backup.sh`), nightly into `./backups`, 14 days; restore into a scratch Postgres tested.
- Production: `docker-compose.prod.yml` + `deploy/Caddyfile.prod` (automatic HTTPS, HSTS); routes shared with share mode in `deploy/caddy/routes.caddy`. Validated, not run on a real domain.
- Shell gotcha: a backslash before `b` or `n` in Windows paths inside `python - <<EOF` snippets became a control character twice; write such text with the Write tool or a script file.

## Gotchas learned

- **Never write regexes or Windows paths through `python - <<EOF` in Bash**: backslashes become control characters or get eaten (happened four times on 2026-10-13). Write code with the Write/Edit tools or a script file in the scratchpad, and grep for control characters afterwards.
- Git Bash rewrites `/tmp/...` and `/backup` in `docker` arguments into Windows paths; prefix with `MSYS_NO_PATHCONV=1`.
- The dev stack is running at the end of this session (`docker compose up -d`, http://localhost:8000); share mode was stopped. Start share mode again with the command in deployment.md when needed.
- Previewing the admin in the built-in browser without typing a password: create a session with `django.test.Client().force_login(user)` in `manage.py shell`, then set the `sessionid` cookie on localhost:8000 via JavaScript.

- textstat needs NLTK's `cmudict` and, for English, crashes instead of falling back when it can't download it at runtime (NLTK 3.10.3's downloader can also reject its own temp file). The Dockerfile now bakes `cmudict` into `/opt/venv/nltk_data` with a SHA-256 check, and `nltk`/`pyphen` are pinned. On 2026-10-13 this left a research step stuck in Running in share mode.
- Anything after an executor returns (saving the version, metrics) is guarded: a metrics failure keeps the output (`metrics_error` in the version metrics), and a save failure marks the step Failed.

- Django 6.1 needs `django.contrib.postgres` in `INSTALLED_APPS` (Wagtail search on Postgres).
- pytest must use `--ds=config.settings.test` (containers set `DJANGO_SETTINGS_MODULE`); test settings use DummyCache, `STUDIO_EXECUTE_STEPS=False`, `STUDIO_QUALITY_SCANS=False`.
- The openai SDK 3.x bundles `httpx2`; tests inject a mock transport through `openai_compat.http_client_factory`.
- Groq rejects Python's default User-Agent (403); every request sends `AI_USER_AGENT`.
- Wagtail's `--w-color-*-50` tints don't switch in dark mode; the studio CSS mixes tints from foreground colours.
- Selects size to their longest option; panel controls are constrained to 100% width.
- Vendored skill scripts are excluded from ruff and must stay byte-identical (re-copy from `~/.claude/skills` to update).
- The `worker` container (db_worker) does not reload code or cached prompt templates: `docker compose restart worker` after changing executors or prompts.
- Docker Desktop must be started manually (`D:\Docker\Docker Desktop.exe`). Your admin user is `sdsmanager`.
