# ADR 0002: Database-backed task queue (django-tasks-db)

- Status: Accepted
- Date: 2026-10-13

## Context

Pipeline steps call LLMs and image models and can run for many minutes. They must run outside web requests, survive restarts and be retryable. Options considered: Celery + Redis, django-q2, and Django's task framework with a database backend.

## Decision

Use Django's task framework (`TASKS` setting) with **`django_tasks_db.DatabaseBackend`** (django-tasks-db 0.13.0) and a `worker` container running `python manage.py db_worker`.

## Rationale

- Wagtail 8 already depends on `django-tasks` for its own background work (reference index, search index).
- On Django 6.1, `django-tasks-db` plugs into the built-in `django.tasks`, while Wagtail enqueues through the `django_tasks` backport. Both read the same `TASKS` setting. **Verified in M1:** publishing a page queued `wagtail.tasks.update_reference_index_task` and `modelsearch.tasks.insert_or_update_object_task` in Postgres, and the worker completed both (`SUCCESSFUL`).
- No extra broker container (Redis/RabbitMQ) to run or back up; the queue lives in Postgres with the content.

## Consequences

- Throughput is lower than Celery's, which is fine for a handful of concurrent generation runs.
- Retries, fallback and scheduling are implemented in the studio's pipeline code (M4) rather than by a Celery feature.
- Tests use `django.tasks.backends.immediate.ImmediateBackend` (`config/settings/test.py`) so tasks run inline.
