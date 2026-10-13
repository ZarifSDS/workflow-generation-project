# Setup

## Prerequisites

| Tool | Notes |
|---|---|
| Docker Desktop (WSL2 engine) | Must show "Engine running" before `docker compose` commands |
| Git | To clone and push |
| Ollama on the host | Optional for M1, required for local models from M2 |
| ComfyUI on the host | Optional, for local image generation from M6 |

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

## 5. Host ComfyUI (local images, M6)

Install the ComfyUI Windows portable build and the FLUX.2 [klein] 4B weights from their official sources. It listens on port 8188. The GPU has 8 GB of VRAM, so the worker unloads the Ollama model before image steps (see [providers.md](providers.md)).

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
