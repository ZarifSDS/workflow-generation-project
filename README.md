# Content Workflow Studio

A self-hosted tool that runs a multi-step content generation pipeline (brief → research → outline → draft → edit → cleanup → hero image → localise) with a human approval gate between steps. It is built on **Wagtail 8 (Django 6.1)** and uses the Wagtail admin as its interface, so drafts, revisions, moderation workflows, images and publishing come built in.

Text and images can come from **local models** (Ollama, ComfyUI) or **free API tiers** (Gemini, Ollama Cloud, Mistral, NVIDIA NIM and others). Each step picks its provider and model from configuration, so models can be swapped without code changes.

> Status: **M1, bootstrap.** The containerised stack, admin shell, Content Studio menu, background worker and docs are in place. The generation pipeline is built in milestones M2–M8 (see [docs/roadmap.md](docs/roadmap.md)).

## Quick start (Windows + Docker Desktop)

```bash
git clone https://github.com/ZarifSDS/workflow-generation-project.git
```

```bash
cd workflow-generation-project
```

```bash
copy .env.example .env
```

Edit `.env` and set `DJANGO_SECRET_KEY` and `POSTGRES_PASSWORD`, then:

```bash
docker compose up -d --build
```

```bash
docker compose exec web python manage.py createsuperuser
```

Open http://localhost:8000/admin/ and find **Content Studio** in the sidebar.

Full instructions, including host setup for Ollama and ComfyUI, are in [docs/setup.md](docs/setup.md).

## Stack

| Service | What it runs |
|---|---|
| `web` | Wagtail/Django (runserver in dev, gunicorn in production) |
| `worker` | `manage.py db_worker`: runs pipeline steps and Wagtail's own background tasks |
| `db` | Postgres 17 (also holds the task queue, via `django-tasks-db`) |
| `migrate` | One-shot container that applies migrations before `web` and `worker` start |
| Host: Ollama, ComfyUI | Local LLMs and image models, using the host GPU and RAM |

## Documentation

- [Architecture](docs/architecture.md)
- [Setup](docs/setup.md)
- [Content workflow](docs/workflow.md)
- [Content Studio UX](docs/ux.md)
- [AI providers](docs/providers.md)
- [Model evaluation](docs/model-eval.md)
- [Roadmap](docs/roadmap.md)
- [Architecture decision records](docs/adr/)

## Development

```bash
docker compose exec web pytest
```

```bash
docker compose exec web ruff check .
```

## Licence

Not yet chosen. Until a licence is added, all rights are reserved by the author.
