"""Remove secrets from text that may be stored or shown (provider errors, step errors, notes).

Provider error messages can echo request URLs (the Cloudflare account ID is in the path) or parts of
an API key. Every configured secret value is replaced before such text is saved or displayed.
"""

import logging
import os
import threading
import time

from django.conf import settings

REDACTED = "[redacted]"
# Environment variables that hold secrets besides the providers' own api_key_env/account_env.
EXTRA_SECRET_ENV = (
    "DJANGO_SECRET_KEY",
    "STUDIO_WEBHOOK_SECRET",
    "NGROK_AUTHTOKEN",
    "POSTGRES_PASSWORD",
    "STUDIO_SECRETS_KEY",
)
MIN_LENGTH = 6  # shorter values would redact ordinary words
STORED_TTL = 60  # seconds a process keeps the decrypted stored keys for redaction

_stored = {"values": (), "at": 0.0}
_busy = threading.local()


def clear_stored_cache():
    _stored["at"] = 0.0


def _stored_values():
    """Keys stored through the admin (ADR 0008), decrypted. Never raises: redaction must always work."""
    if getattr(_busy, "active", False):  # a log line written while we read the database
        return _stored["values"]
    if time.monotonic() - _stored["at"] < STORED_TTL:
        return _stored["values"]
    _busy.active = True
    try:
        from . import secrets
        from .providers import stored_configs

        values = []
        for row in stored_configs():
            for token in (row.api_key_encrypted, row.account_id_encrypted):
                if token:
                    try:
                        values.append(secrets.decrypt(token))
                    except secrets.SecretsUnavailable:
                        pass
        _stored.update(values=tuple(values), at=time.monotonic())
    except Exception:  # noqa: BLE001 - e.g. no database during startup or in tests without one
        pass
    finally:
        _busy.active = False
    return _stored["values"]


def secret_values():
    names = set(EXTRA_SECRET_ENV)
    for config in getattr(settings, "AI_PROVIDERS", {}).values():
        names.update(name for name in (config.get("api_key_env"), config.get("account_env")) if name)
    values = {os.environ.get(name, "").strip() for name in names}
    values.update(value.strip() for value in _stored_values())
    return sorted((value for value in values if len(value) >= MIN_LENGTH), key=len, reverse=True)


class RedactingFilter:
    """Logging filter: secrets in a record's message or traceback are replaced before it's written."""

    def filter(self, record):
        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        return True


def redact(text):
    if not text:
        return text
    text = str(text)
    for value in secret_values():
        if value in text:
            text = text.replace(value, REDACTED)
        # Providers often show a key's first and last characters ("sk-ab...wxyz").
        if len(value) >= 20:
            for fragment in (value[:12], value[-12:]):
                text = text.replace(fragment, REDACTED)
    return text
