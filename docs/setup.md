# Setup

## Prerequisites

| Tool | Notes |
|---|---|
| Docker Desktop (WSL2 engine) | Must show "Engine running" before `docker compose` commands |
| Git | To clone and push |
| Ollama on the host | Optional for M1, required for local models from M2 |
| ComfyUI on the host | Optional, for local hero images (step 6) |

## 1. Clone and configure

```bash
git clone https://github.com/ZarifSDS/workflow-generation-project.git
```

```bash
cd workflow-generation-project
```

```bash
copy .env.example .env
```

In `.env`, set at least:

- `DJANGO_SECRET_KEY`. Generate one with `python -c "import secrets; print(secrets.token_urlsafe(50))"`.
- `POSTGRES_PASSWORD`, any strong value.

## 2. Start the stack

```bash
docker compose up -d --build
```

`docker compose up` automatically applies `docker-compose.override.yml` (development mode):

- dev dependencies (pytest, ruff) are installed
- your source folder is mounted into the containers, so code changes apply without rebuilding
- `web` runs Django's `runserver` with `DEBUG=True`

Check that everything is healthy:

```bash
docker compose ps
```

You should see `db` healthy, `migrate` exited (0), `web` healthy and `worker` running. Then open http://localhost:8000/healthz/, which should return `{"status": "ok", "database": "ok"}`.

## 3. Create your admin user

```bash
docker compose exec web python manage.py createsuperuser
```

Log in at http://localhost:8000/admin/.

## 4. Host Ollama (local models)

Containers reach the host at `http://host.docker.internal:11434`. Recommended host settings: set these as **user environment variables**, then quit and restart Ollama from the system tray.

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_FLASH_ATTENTION` | `1` | Faster attention, less memory |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Halves context memory, so longer research packs fit |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Avoids two large models competing for RAM/VRAM |
| `OLLAMA_HOST` | `0.0.0.0:11434` | Only if containers get "connection refused". Also allow port 11434 through Windows Firewall for private networks. |

The Content Studio overview page shows whether the containers can reach Ollama and ComfyUI.

## 5. Hero branding assets (sds-hero-stock)

The hero step brands generated photos with the vendored sds-hero-stock scripts. Their brand assets (the SDS Manager logo and the measured overlay data) aren't in git because the repository is public ([ADR 0004](adr/0004-brand-assets-outside-git.md)). Copy them from the skill once per clone (Git Bash on the host):

```bash
cp ~/.claude/skills/sds-hero-stock/scripts/assets/*.{png,svg} apps/quality/vendor/sds_hero_stock/assets/
```

The dev containers see them through the source mount; a production build copies them into the image. Without them the hero step still generates and checks the photo, and says that branding was skipped. The Inter Bold font (SIL OFL) is committed.

## 6. Host ComfyUI (local images, optional)

Hero images use Cloudflare by default. To generate them on your PC instead:

1. Install the ComfyUI Windows portable build and the FLUX.2 [klein] 4B weights from their official sources (a quantised build fits the 8 GB GPU). It listens on port 8188.
2. Build a text-to-image workflow in ComfyUI and check that it renders.
3. Export it with **Workflow › Export (API)** and save it as `comfyui/workflows/flux2-klein-4b.json` (the name the model catalog uses; add a catalog entry in `apps/ai/catalog.py` for other workflows).
4. Choose **FLUX.2 klein 4B (ComfyUI)** as the hero image model in the run wizard, or regenerate a hero with it.

The worker patches the exported workflow before queueing it: the prompt text (the text node feeding the sampler's positive input; rename the node to "Positive prompt" if it guesses wrong), the latent width and height (1440×816 for heroes) and the seed. Before each image it unloads Ollama's models (`keep_alive: 0`) so ComfyUI gets the GPU, and afterwards it asks ComfyUI to free its memory (`POST /free`). If ComfyUI isn't running, the step falls back to the image profile's Cloudflare model.

## 7. Publish webhook to n8n (optional)

The Publish step can send each saved draft to an n8n workflow (for example to post to a CMS, notify a channel or file a task):

1. In n8n, add a **Webhook** node (method POST) and copy its production URL.
2. Set it in `.env`: `STUDIO_PUBLISH_WEBHOOK_URL=http://host.docker.internal:5678/webhook/<path>` when n8n runs on the host or in another container with its port published. Optionally set `STUDIO_WEBHOOK_SECRET` and verify `X-Studio-Signature` (`sha256=` + HMAC-SHA256 of the raw body) in n8n.
3. Restart the containers (`docker compose up -d`).

The payload is described in [workflow.md](workflow.md#publish-step-m7). A webhook that fails is reported on the Publish step and doesn't block it.

## Production-style run

Runs gunicorn, without the dev override:

```bash
docker compose -f docker-compose.yml up -d --build
```

Set `DJANGO_ALLOWED_HOSTS` and `DJANGO_CSRF_TRUSTED_ORIGINS` in `.env` for the host name you serve on.

## Everyday commands

| Task | Command |
|---|---|
| Logs | `docker compose logs -f web worker` |
| Run tests | `docker compose exec web pytest` |
| Lint and format | `docker compose exec web ruff check .` and `docker compose exec web ruff format .` |
| New migrations | `docker compose exec web python manage.py makemigrations` |
| Django shell | `docker compose exec web python manage.py shell` |
| Example data for the Content Studio | `docker compose exec web python manage.py studio_demo` (topics start with "[Example]"; rerunning replaces them) |
| Check AI providers | `docker compose exec web python manage.py ai_smoke` (or **Content Studio › Models and providers › Re-check providers**) |
| Stop (keeps data) | `docker compose down` |
| Back up the database | `docker compose exec db pg_dump -U studio studio > backup.sql` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `failed to connect to the docker API` | Start Docker Desktop and wait for "Engine running" |
| `migrate` exits 1 | `docker compose logs migrate` shows the failing check or migration |
| Port 8000 in use | Change the `web` port mapping to `"8001:8000"` |
| Overview shows Ollama "Not reachable" | Start Ollama on the host; see step 4 |
| Tests use the wrong settings | Tests always use `config.settings.test` via `--ds` in `pyproject.toml` |
