# Security

How the studio protects accounts, secrets and data, and the result of the M8 secret handling review (2026-10-13). For running it safely day to day, see [operations.md](operations.md); for exposure over the internet, [deployment.md](deployment.md).

## Accounts and roles

| Group | Can do |
|---|---|
| **Writers** | Use Content Studio; write briefs and start runs; review the writing steps (site crawl, research, outline, draft) and choose title, meta description and slug |
| **Editors** | Everything writers can, plus the editing steps (review and edit, final cleanup, hero image, localise, publish) and exports. Keeps Wagtail's page-editing permissions |
| **Moderators** | Read runs; approve and publish pages through Wagtail's **Moderators approval** workflow |
| **Operators** | Read runs; re-check providers; manage presets; mark a stuck step as failed |
| Superusers | Everything, including user and group management |

- Permissions are checked on every studio request and action, not just hidden in the interface. A user who can't approve a step sees "Ready for review by editors" instead of the buttons.
- Groups are created by migration `studio.0004_m8_groups` and can be changed in **Settings › Groups**, where the four studio permissions are listed with Wagtail's own.
- An admin account with no studio group can't open Content Studio or see it in the menu.
- Passwords need at least 12 characters, and common or numeric-only passwords are rejected.

## Login protection

- **Rate limiting** (django-axes): 5 failed sign-ins for one username from one address lock that combination for 15 minutes, and the person sees a "Too many sign-in attempts" page. Locking by username *and* address means one person's typos can't lock out a whole team behind the same tunnel or office address.
- Behind Caddy (share and production modes), the client address comes from `X-Forwarded-For` with exactly one trusted proxy hop (`DJANGO_PROXY_COUNT=1`); in dev mode it's the direct connection.
- Unlock early: `docker compose exec web python manage.py axes_reset_username <name>` (or `axes_reset` for everyone). Attempts are listed in Django admin at `/django-admin/axes/`.

## Secrets

| Secret | Where it lives | Never in |
|---|---|---|
| `DJANGO_SECRET_KEY`, `POSTGRES_PASSWORD` | `.env` | git, the database, logs |
| Provider keys (`GEMINI_API_KEY`, `OLLAMA_CLOUD_API_KEY`, `GROQ_API_KEY`, `CLOUDFLARE_API_TOKEN`) and `CLOUDFLARE_ACCOUNT_ID` | `.env`, read at call time | the database, logs, step errors, notes |
| `STUDIO_WEBHOOK_SECRET` | `.env` | the webhook payload (only its HMAC is sent) |
| ngrok authtoken | The ngrok agent's own config, mounted read-only (`NGROK_CONFIG_FILE`), or `NGROK_AUTHTOKEN` in `.env` | git, the images |

## Secret handling review (M8, 2026-10-13)

| Area | Finding | Result |
|---|---|---|
| Git history | gitleaks over every commit | No secrets found. CI now runs the scan on every push (`secret-scan` job) |
| Settings | Production refuses to start without `DJANGO_SECRET_KEY`; the insecure fallback key, `DEBUG` and `ALLOWED_HOSTS=*` exist only in dev settings, which share and production modes don't use | OK |
| Provider errors | Error text from providers can echo request URLs (the Cloudflare account ID is in the path) or parts of a key, and it was stored in step errors, provider-check results and version notes | **Fixed:** every `ProviderError` message, every failed step's error and every log line passes through `apps.ai.redact`, which replaces configured secret values and the first and last 12 characters of long keys with `[redacted]` |
| Logs | httpx and openai request logging was already at WARNING (URLs contain the account ID) | Kept, plus the redacting log filter on the console handler |
| Webhook | Payload signed with HMAC-SHA256 when a secret is set; the secret itself is never sent | OK |
| Database | Keys aren't stored; provider checks store only a redacted status line | OK after the redaction fix |
| Brand assets | Kept out of the public repository (ADR 0004) | OK |
| Public tunnel URL | Was in the handoff doc of the public repository | Removed before it was committed |
| `docker compose config` | Prints every `.env` value | Documented: use `config --quiet` to validate |
| Default database password | Compose falls back to `studio` if `POSTGRES_PASSWORD` is unset; the database publishes no host port | Set a strong value in `.env` anyway |

## Rotating a secret

1. Change the value in `.env` (or at the provider, then in `.env`).
2. `docker compose up -d` (or the share/production command) so the containers pick it up.
3. For `DJANGO_SECRET_KEY`: everyone is signed out. For `POSTGRES_PASSWORD`: also change it inside Postgres first: `docker compose exec db psql -U studio -c "ALTER USER studio PASSWORD '<new>'"`.

## Data and model output

- Model output is untrusted. It's rendered as Markdown and then sanitised (nh3) before it's shown in the admin, exported or put on a page; scripts, images and unsafe links are dropped.
- Free model tiers may use prompts for training: no confidential material in briefs or notes.
- Images under `/media/` are public by URL, as in any Wagtail site (including heroes of drafts).
- Backups (`./backups`) contain the whole database, including password hashes. Keep that folder private.
