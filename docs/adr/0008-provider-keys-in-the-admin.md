# ADR 0008: Provider API keys stored through the admin, encrypted

- Status: Accepted
- Date: 2026-10-13
- Amends: [ADR 0003](0003-provider-registry.md) ("API keys come only from environment variables")

## Context

Keys for the free providers were added by hand to `.env`. The team wants to add paid providers (OpenRouter and others) and their keys from the web app, without shell access, and to replace or remove keys there. Keys must not be readable in the app afterwards.

## Decision

- **Superusers only**: Settings › AI providers. Operators keep managing models and checks on the Content Studio screen, but can't see or change keys. Permission is checked before any lookup.
- **Encrypted at rest** with Fernet under `STUDIO_SECRETS_KEY`, which lives in `.env` and never in the database. Database dumps and the nightly backups contain ciphertext only. Several comma-separated keys allow rotation (`manage.py rotate_provider_keys`). Without the key, nothing can be stored and the page says why; there is no plaintext fallback.
- **Write-only**: the key field is a password input that never renders a value, pages are `no-store`, and only the last four characters are kept as a hint (`••••abcd`). Keys under 13 characters show no characters at all.
- **Precedence**: a stored key replaces the provider's environment variable; removing it falls back to `.env`. Existing `.env` setups keep working unchanged.
- **Added providers** are OpenAI-compatible only, need `https` (plain `http` only for this machine or the Docker host), and may not reuse a built-in id. **Changing an added provider's address removes its stored key** unless the key is entered again in the same save, so a key can't be redirected to another server.
- **Added models** appear in the model lists; adding a paid model is the opt-in, so it is selectable. Built-in paid models stay off.
- **Removal**: a stored key, an added provider (with its models) and an added model can each be removed, after a confirmation page.
- **Audit**: every change is a Wagtail history entry (Reports › Site history) naming the user; entries hold at most the last four characters.
- **Redaction** (`apps.ai.redact`) also covers stored keys and `STUDIO_SECRETS_KEY`.

## Consequences

- A stolen database or backup alone doesn't give the keys; `.env` plus the database does. Back up `.env` separately from `backups/`.
- Anyone with a superuser account can *use* and *replace* keys (not read them). Keep superusers few; consider two-factor sign-in before exposing the admin publicly.
- Losing `STUDIO_SECRETS_KEY` means re-entering the stored keys.
