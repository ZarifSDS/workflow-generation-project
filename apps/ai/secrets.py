"""Encryption for provider API keys stored through the admin (ADR 0008).

Keys are encrypted with Fernet (AES-128-CBC + HMAC-SHA256) under STUDIO_SECRETS_KEY, which lives in .env,
never in the database. Database dumps and backups therefore hold only ciphertext. STUDIO_SECRETS_KEY may
list several comma-separated keys: the first encrypts, all of them decrypt (for rotation).
"""

import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

ENV_NAME = "STUDIO_SECRETS_KEY"
HINT_LENGTH = 4


class SecretsUnavailable(Exception):
    """STUDIO_SECRETS_KEY is missing or wrong, so stored keys can't be written or read."""


def _keys():
    return [key.strip() for key in os.environ.get(ENV_NAME, "").split(",") if key.strip()]


def available():
    try:
        _fernet()
    except SecretsUnavailable:
        return False
    return True


def _fernet():
    keys = _keys()
    if not keys:
        raise SecretsUnavailable(f"{ENV_NAME} is not set in .env, so API keys can't be stored or read.")
    try:
        return MultiFernet([Fernet(key) for key in keys])
    except ValueError:
        raise SecretsUnavailable(f"{ENV_NAME} in .env is not a valid key (see docs/security.md).") from None


def encrypt(value):
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token):
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        raise SecretsUnavailable(
            f"A stored API key can't be decrypted: {ENV_NAME} changed. Enter the key again."
        ) from None


def hint(value):
    """What the admin shows of a key: its last few characters only."""
    value = value.strip()
    return f"••••{value[-HINT_LENGTH:]}" if len(value) > HINT_LENGTH * 3 else "••••"


def generate_key():
    return Fernet.generate_key().decode()
