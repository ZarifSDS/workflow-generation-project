# Content Workflow Studio

A self-hosted tool that runs a multi-step content generation pipeline (brief → research → outline → draft → review and edit → cleanup → hero image → localise → publish) with a human approval gate between steps. It is built on **Wagtail 8 (Django 6.1)** and uses the Wagtail admin as its interface, so drafts, revisions, moderation workflows, images and publishing come built in.

Text and images come from **local models** (Ollama, ComfyUI) or **free API tiers** (Ollama Cloud, Gemini, Groq, Cloudflare Workers AI). Each step picks its provider and model from configuration, so models can be swapped without code changes.

> Status: **M1–M7 built** (pipeline, review sequence, branded hero images, publishing into Wagtail moderation, exports). M8 (hardening) is next, and model defaults are interim until the evaluation is scored. See [docs/roadmap.md](docs/roadmap.md).

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

Start with **[Tools and processes](docs/tools-and-processes.md)**, then the guide for your role:

- [User guide](docs/user-guide.md): writers, editors, moderators
- [Operations guide](docs/operations.md): running and maintaining the studio
- [Development guide](docs/development.md): developers and AI agents
- [Deployment](docs/deployment.md): sharing over ngrok and scaling

Reference:

- [Architecture](docs/architecture.md)
- [Setup](docs/setup.md)
- [Content workflow](docs/workflow.md)
- [Content Studio UX](docs/ux.md)
- [AI providers](docs/providers.md)
- [Model evaluation](docs/model-eval.md)
- [Roadmap](docs/roadmap.md)
- [Architecture decision records](docs/adr/)
- [Session handoff](docs/HANDOFF.md)

## Development

```bash
docker compose exec web pytest
```

```bash
docker compose exec web ruff check .
```

## Licence

Not yet chosen. Until a licence is added, all rights are reserved by the author.
