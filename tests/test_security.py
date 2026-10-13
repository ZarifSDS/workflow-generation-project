"""M8: secret redaction and login rate limiting."""

import logging

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.ai.redact import REDACTED, RedactingFilter, redact
from apps.ai.types import ProviderError
from apps.studio import executors

KEY = "gsk_test_0123456789abcdefghijklmnopqrstuv"
ACCOUNT = "acct0123456789abcdef"


@pytest.fixture
def secrets(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", KEY)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", ACCOUNT)


def test_redact_replaces_keys_account_ids_and_key_fragments(secrets):
    url = f"https://api.cloudflare.com/accounts/{ACCOUNT}/ai/run"
    text = f"401 for {url} with key {KEY} ({KEY[:12]}...{KEY[-12:]})"
    cleaned = redact(text)
    assert KEY not in cleaned and ACCOUNT not in cleaned
    assert KEY[:12] not in cleaned and KEY[-12:] not in cleaned
    assert cleaned.count(REDACTED) >= 3


def test_provider_errors_and_step_errors_are_redacted(secrets):
    error = ProviderError("auth", f"Incorrect API key provided: {KEY}", 401)
    assert KEY not in str(error)
    assert KEY not in executors.friendly_error(error)


def test_log_records_are_redacted(secrets):
    record = logging.LogRecord("x", logging.WARNING, __file__, 1, "call to %s failed", (ACCOUNT,), None)
    RedactingFilter().filter(record)
    assert ACCOUNT not in record.getMessage()


def test_short_or_unset_values_are_left_alone(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "abc")
    assert redact("abc and more") == "abc and more"


@pytest.mark.django_db
def test_login_locks_after_five_failures_per_username_and_address(client):
    get_user_model().objects.create_user("editor", password="right-test-password", is_superuser=True)
    url = reverse("wagtailadmin_login")
    for _ in range(5):
        client.post(url, {"username": "editor", "password": "wrong-test-password"})
    locked = client.post(url, {"username": "editor", "password": "right-test-password"})
    assert locked.status_code == 429
    assert "Too many sign-in attempts" in locked.text

    # Another username from the same address isn't affected.
    get_user_model().objects.create_user("writer", password="writer-test-password", is_superuser=True)
    ok = client.post(url, {"username": "writer", "password": "writer-test-password"})
    assert ok.status_code == 302


def test_passwords_need_twelve_characters():
    from django.contrib.auth.password_validation import validate_password
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        validate_password("Short-pw-11")
    validate_password("long-enough-pass-phrase")
