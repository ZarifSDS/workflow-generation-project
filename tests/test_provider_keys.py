"""ADR 0008: provider API keys stored through the admin, encrypted, write-only, superusers only."""

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.db import connection
from django.urls import reverse

from apps.ai import catalog, redact, secrets
from apps.ai.models import AddedModel, ProviderConfig
from apps.ai.providers import get_provider, get_providers
from apps.ai.types import ProviderError

pytestmark = pytest.mark.django_db

KEY = "sk-or-v1-0123456789abcdefFAKEFAKEtestonly9f3e"
GROQ_KEY = "gsk_FAKEtestonlyKEYvalue1234567890wxyz"


@pytest.fixture(autouse=True)
def secrets_key(monkeypatch):
    monkeypatch.setenv(secrets.ENV_NAME, Fernet.generate_key().decode())
    redact.clear_stored_cache()
    yield
    redact.clear_stored_cache()


def _operator():
    user = get_user_model().objects.create_user("operator", password="unused-test-password")
    user.groups.add(Group.objects.get(name="Operators"))
    return user


def _add_openrouter(admin_client, key=KEY):
    return admin_client.post(
        reverse("studio:provider_add"),
        {
            "label": "OpenRouter",
            "name": "openrouter",
            "base_url": "https://openrouter.ai/api/v1/",
            "api_key": key,
        },
    )


# ---- encryption ----


def test_encrypt_round_trip_and_hint():
    token = secrets.encrypt(KEY)
    assert KEY not in token and secrets.decrypt(token) == KEY
    assert secrets.hint(KEY) == "••••9f3e"
    assert secrets.hint("short") == "••••"


def test_rotation_with_several_keys(monkeypatch):
    old = Fernet.generate_key().decode()
    monkeypatch.setenv(secrets.ENV_NAME, old)
    token = secrets.encrypt(KEY)
    ProviderConfig.objects.create(name="groq", label="Groq", api_key_encrypted=token)
    monkeypatch.setenv(secrets.ENV_NAME, f"{Fernet.generate_key().decode()},{old}")
    assert secrets.decrypt(token) == KEY  # the old key still decrypts
    call_command("rotate_provider_keys", stdout=open("/dev/null", "w"))
    monkeypatch.setenv(secrets.ENV_NAME, secrets._keys()[0])  # drop the old key
    assert secrets.decrypt(ProviderConfig.objects.get(name="groq").api_key_encrypted) == KEY


def test_without_the_secrets_key_nothing_is_stored(monkeypatch, admin_client):
    monkeypatch.delenv(secrets.ENV_NAME)
    assert not secrets.available()
    page = admin_client.get(reverse("studio:provider_keys")).text
    assert "Keys can&#x27;t be stored yet" in page or "Keys can't be stored yet" in page
    admin_client.post(reverse("studio:provider_key", args=["groq"]), {"api_key": GROQ_KEY})
    assert not ProviderConfig.objects.exists()


# ---- storing, showing, removing ----


def test_stored_key_is_encrypted_in_the_database(admin_client):
    response = admin_client.post(reverse("studio:provider_key", args=["groq"]), {"api_key": GROQ_KEY})
    assert response.status_code == 302
    row = ProviderConfig.objects.get(name="groq")
    assert row.api_key_hint == "••••wxyz"
    with connection.cursor() as cursor:  # what a database dump or backup would contain
        cursor.execute("SELECT * FROM ai_providerconfig")
        dumped = repr(cursor.fetchall())
    assert GROQ_KEY not in dumped and GROQ_KEY[:12] not in dumped


def test_key_is_never_shown_again(admin_client):
    admin_client.post(reverse("studio:provider_key", args=["groq"]), {"api_key": GROQ_KEY})
    for url in (reverse("studio:provider_keys"), reverse("studio:provider_key", args=["groq"])):
        page = admin_client.get(url).text
        assert GROQ_KEY not in page and GROQ_KEY[:12] not in page
    assert "••••wxyz" in admin_client.get(reverse("studio:provider_keys")).text
    form = admin_client.get(reverse("studio:provider_key", args=["groq"])).text
    assert 'type="password"' in form and 'autocomplete="new-password"' in form


def test_key_pages_are_not_cached(admin_client):
    response = admin_client.get(reverse("studio:provider_keys"))
    assert "no-store" in response["Cache-Control"]


def test_stored_key_wins_over_env_and_removal_falls_back(admin_client, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_env_key_FAKE_testonly_000000")
    assert get_providers()["groq"].key_source == "env"
    admin_client.post(reverse("studio:provider_key", args=["groq"]), {"api_key": GROQ_KEY})
    spec = get_provider("groq")
    assert spec.key_source == "studio" and spec.api_key == GROQ_KEY
    admin_client.post(reverse("studio:provider_key_remove", args=["groq"]))
    assert not ProviderConfig.objects.filter(name="groq").exists()
    assert get_provider("groq").api_key == "gsk_env_key_FAKE_testonly_000000"


def test_remove_asks_first(admin_client):
    admin_client.post(reverse("studio:provider_key", args=["groq"]), {"api_key": GROQ_KEY})
    page = admin_client.get(reverse("studio:provider_key_remove", args=["groq"])).text
    assert "Remove the stored key for" in page
    assert ProviderConfig.objects.filter(name="groq").exists()


def test_bad_keys_are_rejected(admin_client):
    for bad in ("short", "has a space inside it"):
        response = admin_client.post(reverse("studio:provider_key", args=["groq"]), {"api_key": bad})
        assert response.status_code == 200
    assert not ProviderConfig.objects.exists()


def test_cloudflare_account_id_is_stored_encrypted_too(admin_client):
    admin_client.post(
        reverse("studio:provider_key", args=["cloudflare"]),
        {"api_key": "cf_FAKE_testonly_token_1234567", "account_id": "0123456789abcdef0123456789abcdef"},
    )
    spec = get_providers()["cloudflare"]
    assert spec.account_id == "0123456789abcdef0123456789abcdef" and spec.is_configured


def test_changes_are_in_the_history_without_the_key(admin_client):
    from wagtail.models import ModelLogEntry

    admin_client.post(reverse("studio:provider_key", args=["groq"]), {"api_key": GROQ_KEY})
    entry = ModelLogEntry.objects.get(action="ai.key_set")
    assert entry.user.is_superuser and GROQ_KEY not in repr(entry.data)


# ---- added providers and models ----


def test_add_openrouter_with_a_paid_model(admin_client):
    assert _add_openrouter(admin_client).status_code == 302
    spec = get_provider("openrouter")
    assert spec.adapter == "openai_compat" and spec.base_url == "https://openrouter.ai/api/v1"
    assert spec.api_key == KEY
    admin_client.post(
        reverse("studio:provider_model_add"),
        {"provider": "openrouter", "model": "openai/gpt-5.5", "label": "GPT-5.5", "status": "paid"},
    )
    item = catalog.by_key("openrouter::openai/gpt-5.5")
    assert item.selectable and item.added
    groups = dict(catalog.grouped("text"))
    assert "OpenRouter" in groups and item in groups["OpenRouter"]


def test_built_in_paid_models_stay_off():
    assert not catalog.find("gemini", "gemini-pro-latest").selectable


def test_changing_the_address_drops_the_key(admin_client):
    _add_openrouter(admin_client)
    admin_client.post(
        reverse("studio:provider_edit", args=["openrouter"]),
        {"label": "OpenRouter", "base_url": "https://evil.example.com/v1"},
    )
    row = ProviderConfig.objects.get(name="openrouter")
    assert row.base_url == "https://evil.example.com/v1" and not row.api_key_encrypted
    with pytest.raises(ProviderError, match="needs a key"):
        get_provider("openrouter")


@pytest.mark.parametrize(
    "url",
    [
        "http://openrouter.ai/api/v1",
        "https://user:pw@openrouter.ai/v1",
        "https://x.example/v1?a=1",
        "ftp://x/",
    ],
)
def test_unsafe_addresses_are_refused(admin_client, url):
    response = admin_client.post(
        reverse("studio:provider_add"), {"label": "X", "name": "x", "base_url": url, "api_key": KEY}
    )
    assert response.status_code == 200 and not ProviderConfig.objects.filter(name="x").exists()


def test_local_http_is_allowed(admin_client):
    admin_client.post(
        reverse("studio:provider_add"),
        {
            "label": "LM Studio",
            "name": "lmstudio",
            "base_url": "http://host.docker.internal:1234/v1",
            "api_key": KEY,
        },
    )
    assert ProviderConfig.objects.filter(name="lmstudio").exists()


def test_built_in_ids_cant_be_added(admin_client):
    admin_client.post(
        reverse("studio:provider_add"),
        {"label": "Groq", "name": "groq", "base_url": "https://evil.example.com/v1", "api_key": KEY},
    )
    assert not ProviderConfig.objects.filter(name="groq").exists()


def test_delete_provider_removes_its_models(admin_client):
    _add_openrouter(admin_client)
    AddedModel.objects.create(provider="openrouter", model="x/y", label="Y")
    admin_client.post(reverse("studio:provider_delete", args=["openrouter"]))
    assert not ProviderConfig.objects.exists() and not AddedModel.objects.exists()
    assert "openrouter" not in get_providers()


def test_remove_model(admin_client):
    item = AddedModel.objects.create(provider="groq", model="x/y", label="Y")
    admin_client.post(reverse("studio:provider_model_remove", args=[item.pk]))
    assert not AddedModel.objects.exists() and catalog.find("groq", "x/y") is None


# ---- who may ----


@pytest.mark.parametrize(
    "name, args",
    [("provider_keys", []), ("provider_key", ["groq"]), ("provider_add", []), ("provider_model_add", [])],
)
def test_only_superusers(client, name, args):
    client.force_login(_operator())  # operators manage models, but not keys
    assert client.get(reverse(f"studio:{name}", args=args)).status_code in (302, 403)
    response = client.post(reverse("studio:provider_key", args=["groq"]), {"api_key": GROQ_KEY})
    assert response.status_code in (302, 403) and not ProviderConfig.objects.exists()


def test_menu_item_only_for_superusers(client, admin_client):
    url = reverse("studio:provider_keys")
    assert url in admin_client.get(reverse("wagtailadmin_home")).text
    client.force_login(_operator())
    assert url not in client.get(reverse("wagtailadmin_home")).text


# ---- redaction ----


def test_stored_keys_are_redacted(admin_client):
    admin_client.post(reverse("studio:provider_key", args=["groq"]), {"api_key": GROQ_KEY})
    redact.clear_stored_cache()
    assert GROQ_KEY not in redact.redact(f"401 Unauthorized: key {GROQ_KEY} rejected")
    assert GROQ_KEY[:12] not in redact.redact(f"key starting {GROQ_KEY[:12]}")
