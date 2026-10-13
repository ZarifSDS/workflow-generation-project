# Operations guide: running the studio

For whoever keeps the studio running: starting and stopping it, configuration, providers and models, backups, updates and troubleshooting. First-time installation is in [setup.md](setup.md); sharing over ngrok and scaling are in [deployment.md](deployment.md); this guide covers the day-to-day.

## What runs where

| Part | Where | Notes |
|---|---|---|
| `web` | Docker | Wagtail admin and site. Dev: runserver with live code; production: gunicorn |
| `worker` | Docker | Runs pipeline steps and Wagtail's background tasks (`manage.py db_worker`) |
| `db` | Docker | Postgres 17: content, run history and the task queue. Volume `workflow-generation-project_pgdata` |
| `migrate` | Docker | Applies migrations on every start, then exits |
| Media | Docker volume `workflow-generation-project_media` | Uploaded and generated images (hero photos and branded heroes) |
| `proxy`, `ngrok` | Docker, share mode only | Caddy in front of web, and the HTTPS tunnel ([deployment.md](deployment.md)) |
| Ollama | Windows host, port 11434 | Local text and vision models |
| ComfyUI | Windows host, port 8188 | Optional local image generation |
| Cloud providers | Internet | Ollama Cloud, Gemini, Groq, Cloudflare Workers AI (free tiers; keys in `.env`) |
| n8n | Optional, anywhere reachable | Receives the publish webhook |

## Daily start and stop

1. Start Docker Desktop (`D:\Docker\Docker Desktop.exe`) and wait for "Engine running". It doesn't start on its own.
2. Start Ollama from the Start menu if you'll use local models.
3. Start the stack:

```bash
docker compose up -d
```

4. Check it: `docker compose ps` should show `db` healthy, `migrate` exited (0), `web` healthy and `worker` running. The Content Studio dashboard's **Services** panel shows whether Ollama and ComfyUI are reachable.

Stop with `docker compose down` (data is kept in the volumes). Long runs survive a restart: a queued step waits in the database until the worker is back.

## Configuration (`.env`)

Secrets live only in `.env` (never in git, the database or logs). After changing it, run `docker compose up -d` so the containers pick it up.

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Required. Long random value |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | Production: the host names you serve on |
| `DJANGO_SECURE_COOKIES` | `true` when served over HTTPS |
| `WAGTAILADMIN_BASE_URL` | Base URL used in links (notifications, the webhook's `admin_url`) |
| `TIME_ZONE`, `LOG_LEVEL` | Optional |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Database credentials |
| `OLLAMA_BASE_URL`, `COMFYUI_BASE_URL` | Host services; defaults use `host.docker.internal` |
| `GEMINI_API_KEY`, `OLLAMA_CLOUD_API_KEY`, `GROQ_API_KEY` | Free text providers |
| `CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_API_TOKEN` | Cloudflare Workers AI (hero images) |
| `STUDIO_PUBLISH_WEBHOOK_URL`, `STUDIO_WEBHOOK_SECRET` | Optional publish webhook and its signing secret |
| `NGROK_CONFIG_FILE` or `NGROK_AUTHTOKEN`, `NGROK_DOMAIN`, `STUDIO_PUBLIC_URL`, `GUNICORN_WORKERS` | Share mode ([deployment.md](deployment.md)) |
| `NVIDIA_API_KEY`, `MISTRAL_API_KEY`, `OPENROUTER_API_KEY` | Listed for completeness; not usable in this deployment |

## Providers and models

- **Check providers:** **Content Studio › Models and providers › Re-check providers**, or `docker compose exec web python manage.py ai_smoke`. Each provider gets one tiny call; the result is stored and shown on that screen.
- **Free only.** Every provider runs on a free tier or locally. Limits (verified 2026-10-13, see [providers.md](providers.md)): Groq's Qwen 27B allows 1,000 output tokens a minute; Cloudflare gives 10,000 neurons a day (about 95 FLUX.2 klein images); Gemini Flash sometimes returns "high demand" or server errors, which are retried and then covered by the fallback model. Pro models have no free quota.
- **Profiles** map each step to a model and a fallback: `quality` (outline, draft, localise), `fast` (research, site crawl, hero prompt), `edit` (review and edit), `image` (hero photo) and `vision` (hero check). They're set in `AI_PROFILES` in `config/settings/base.py`. Users can override the model per run and per step from the dropdowns, which list the models in `apps/ai/catalog.py`.
- **Choosing defaults** is an evaluation process, not a leaderboard pick: blind-score real outputs, then set the profiles. See [model-eval.md](model-eval.md). The current defaults are interim until the outline round is scored.
- **Local models and VRAM:** the GPU has 8 GB, so large models spill into system RAM and are slower (Qwen3.8 27B takes about 19 minutes per outline). Recommended Ollama settings are in [setup.md](setup.md#4-host-ollama-local-models). Before a ComfyUI image, the worker unloads Ollama's models and afterwards asks ComfyUI to free its memory.

## Hero branding assets and ComfyUI

- The SDS Manager logo and overlay data are **not in git** (public repository, [ADR 0004](adr/0004-brand-assets-outside-git.md)). After a fresh clone, copy them from the skill ([setup.md step 5](setup.md#5-hero-branding-assets-sds-hero-stock)); without them heroes come out unbranded with a note saying why.
- ComfyUI is optional ([setup.md step 6](setup.md#6-host-comfyui-local-images-optional)). If it isn't running, hero steps that chose it fall back to Cloudflare.

## Publish webhook (n8n)

Set `STUDIO_PUBLISH_WEBHOOK_URL` to an n8n Webhook node URL ([setup.md step 7](setup.md#7-publish-webhook-to-n8n-optional)). Every saved draft is POSTed as JSON (payload in [workflow.md](workflow.md#publish-step-m7)). With `STUDIO_WEBHOOK_SECRET`, verify `X-Studio-Signature` in n8n. A failing webhook shows on the Publish step and never blocks publishing.

## Backups and restore

Back up **both** the database and the media volume; one without the other loses either the runs or their images.

```bash
docker compose exec -T db pg_dump -U studio studio > backup-db.sql
```

```bash
docker run --rm -v workflow-generation-project_media:/media -v "%cd%":/backup alpine tar czf /backup/backup-media.tgz -C /media .
```

Restore onto empty volumes. `docker compose down -v` **deletes the current database and media**, so only run it when you mean to replace them:

```bash
docker compose down -v
```

```bash
docker compose up -d db
```

```bash
docker compose exec -T db psql -U studio studio < backup-db.sql
```

```bash
docker run --rm -v workflow-generation-project_media:/media -v "%cd%":/backup alpine tar xzf /backup/backup-media.tgz -C /media
```

Then start everything with `docker compose up -d`. Also keep `.env` somewhere safe (a password manager), since it isn't in git. Automated backups are planned for M8.

## Updating

1. `git pull`
2. `docker compose up -d --build` (rebuilds when `requirements.txt` changed; migrations run automatically).
3. **Restart the worker after any code or prompt change**: `docker compose restart worker`. It doesn't reload code, and it caches prompt templates. The dev `web` container reloads by itself.

### Updating the vendored skill scripts

The quality and hero scripts are copied **unchanged** from the Claude Code skills in `~/.claude/skills/` into `apps/quality/vendor/`. To update, copy the new versions over the old ones (never edit them in place), run the tests, and commit:

| Skill | Vendored folder |
|---|---|
| deslop | `apps/quality/vendor/deslop/` |
| clarity-review | `apps/quality/vendor/clarity_review/` |
| clean-user-facing-text | `apps/quality/vendor/clean_user_facing_text/` |
| ehs-seo-blog-optimized | `apps/quality/vendor/ehs_seo_blog/` |
| sds-hero-stock | `apps/quality/vendor/sds_hero_stock/` (scripts and font; brand assets stay local) |

## Disk space

Docker's virtual disk lives on **D:** (`D:\DockerData`, moved there on 2026-10-13 via **Docker Desktop › Settings › Resources › Advanced › Disk image location**), and the Hugging Face and sds-hero caches are in `D:\caches` behind links at their old paths. Keep at least 15 GB free on C: anyway: when C: filled up on 2026-10-13, Docker crashed and kept trying to reformat its disk on restart, and only a full `wsl --shutdown` brought it back. If Docker loops on "Starting the Docker Engine":

1. Quit Docker Desktop (`docker desktop stop`).
2. Free space, then copy `docker_data.vhdx` somewhere safe before anything else.
3. `wsl --shutdown`, then start Docker Desktop again.

`docker system df` shows what Docker can reclaim; `docker builder prune -a` and `docker image prune -a` free build cache and unused images without touching volumes.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `failed to connect to the docker API` | Start Docker Desktop and wait for "Engine running" |
| A step stays **Queued** | The worker isn't running: `docker compose ps`, then `docker compose up -d worker`; check `docker compose logs worker` |
| A step stays **Running** after a worker restart | It was interrupted and won't finish on its own. A developer requeues it ([development.md](development.md#requeue-a-stuck-or-approved-step)) |
| "Couldn't reach the provider" with a local model | Start Ollama; check the dashboard's Services panel |
| "The free limit for this model was reached" | Wait for the limit to reset or pick another model |
| "This provider isn't set up" | Add its key to `.env` and run `docker compose up -d` |
| Hero "Branding skipped: the brand assets aren't installed" | Copy the assets (setup step 5) |
| A changed prompt or code has no effect on steps | `docker compose restart worker` |
| `migrate` exits 1 | `docker compose logs migrate` shows the failing migration or check |
| Overview shows Ollama "Not reachable" | Start Ollama; if it still fails, see the `OLLAMA_HOST` note in [setup.md](setup.md#4-host-ollama-local-models) |

## Security notes

- Free tiers may use prompts for training: no confidential material in briefs or notes.
- API keys come only from `.env`; they're never stored in the database or written to logs (request URL logging is turned down because Cloudflare URLs contain the account ID).
- Model output is untrusted: it's sanitised before it's shown in the admin, exported or put on a page.
- The repository is public. Never commit `.env`, keys, brand assets or exported customer material.
- Roles and permissions, a secrets review, automated backups and a production compose file are M8 (see [roadmap.md](roadmap.md)).
