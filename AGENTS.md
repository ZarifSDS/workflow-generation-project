# Agent instructions

Guidance for AI coding agents (Claude Code, Codex, Hermes, Copilot) working in this repository.

## What this is

Content Workflow Studio: a Wagtail 8 / Django 6.1 app that runs a content generation pipeline with human approval gates. Read `docs/architecture.md` and `docs/workflow.md` before larger changes, and `docs/roadmap.md` for which milestone is in progress.

## Layout

- `config/`: project package. Settings live in `config/settings/{base,dev,production,test}.py`.
- `apps/studio/`: Content Studio admin (menu, views, pipeline).
- `apps/ai/`: provider layer and model evaluation. `apps/quality/`: vendored skill scripts and their wrappers.
- `apps/content/`: `ArticlePage`, publishing and exports.
- `apps/home/`, `apps/search/`: Wagtail starter apps.
- `tests/`: pytest-django tests.
- `docs/`: architecture, setup, workflow, providers, ADRs.

## Running things

Everything runs in Docker. Do not install packages on the host Python.

- Start: `docker compose up -d --build`
- Tests: `docker compose exec web pytest`
- Lint: `docker compose exec web ruff check .` and `docker compose exec web ruff format --check .`
- Migrations: `docker compose exec web python manage.py makemigrations` (commit the generated files)

## Conventions

- Extend Wagtail through hooks, viewsets and template components. Never patch Wagtail's code.
- New Content Studio menu entries register on the `register_studio_menu_item` hook (see `apps/studio/wagtail_hooks.py`).
- Long-running work (LLM calls, image generation) runs as Django tasks (`TASKS` setting, `django_tasks_db` backend), never in a request.
- AI calls go through the provider layer (`apps/ai/`, M2). Never hard-code a provider or model in a pipeline step; use a profile (`quality`, `fast`, `edit`, `image`, `vision`).
- Secrets come only from environment variables. Never commit `.env`, keys or tokens, and never write keys into the database, logs or fixtures.
- Pin dependencies exactly in `requirements*.txt` and verify they resolve inside the container before committing.
- Add or update tests with every behaviour change; keep `ruff check` clean (line length 110).
- Update the relevant doc in `docs/` when behaviour, setup or architecture changes; record significant decisions as a new ADR.

## Gotchas

- The containers set `DJANGO_SETTINGS_MODULE`; pytest forces `config.settings.test` via `--ds` in `pyproject.toml`.
- Ollama and ComfyUI run on the Windows host and are reached at `host.docker.internal`.
- On Django 6.1 with Postgres, `django.contrib.postgres` must stay in `INSTALLED_APPS` (Wagtail search index).
