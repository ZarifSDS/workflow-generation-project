# ADR 0005: Containerised share mode behind Caddy and ngrok, built to scale out

- Status: Accepted
- Date: 2026-10-13

## Context

The studio has to be usable by other people now, as a test version, without a server or domain, and should be able to grow into a real deployment without a redesign. Until now it only ran in dev mode (runserver, `DEBUG` on), which must never face the internet.

## Decision

- A second compose file, `docker-compose.share.yml`, layers onto the production `docker-compose.yml`: gunicorn with production settings, `DEBUG` off, secure cookies, `SECURE_PROXY_SSL_HEADER` (opt-in via `DJANGO_BEHIND_PROXY`).
- **Caddy** sits in front of the web containers: it serves the media volume and load-balances over every `web` replica found by DNS. Web containers publish no host port, so they scale with `--scale`.
- **ngrok** runs as a container and tunnels HTTPS to Caddy. It reuses the operator's existing ngrok agent config (mounted read-only) or an authtoken from `.env`; the account's free static domain needs no configuration. Allowed hosts and CSRF origins accept ngrok's domain suffixes.
- **Workers scale** horizontally: `django-tasks-db` claims tasks with `SKIP LOCKED`, and `execute_step` locks the step and runs it only while queued.
- State lives only in Postgres and the media volume. Everything else is stateless and rebuildable from the image.
- Images are pinned: `caddy:2.11.4-alpine`, `ngrok/ngrok:3.39.11-alpine`.

## Consequences

- Dev and share modes use the same services and volumes; switching keeps all data, but only one mode runs at a time.
- The admin login is public in share mode, so strong passwords matter until M8 adds rate limiting and studio permissions.
- Scaling beyond one machine needs object storage for media and a managed or dedicated Postgres; the containers, settings and proxy stay the same (see `docs/deployment.md`).
- Free ngrok shows an interstitial page on first visit and has usage limits; a real domain with TLS replaces it when the studio moves to a server.
