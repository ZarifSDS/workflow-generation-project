"""The providers' own model lists (apps/ai/remote_models.py): read for a stored key into the model
dropdowns automatically, and managed by hand (add several, rename, re-price, remove, restore)."""

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from django.urls import reverse

from apps.ai import catalog, redact, remote_models, secrets
from apps.ai.models import AddedModel, ModelSync
from apps.ai.providers import ProviderSpec, get_provider

pytestmark = pytest.mark.django_db

KEY = "sk-or-v1-FAKEtestonlyKEY0123456789abcdef"
OPENROUTER_MODELS = {
    "data": [
        {
            "id": "meta-llama/llama-4-scout:free",
            "name": "Meta: Llama 4 Scout (free)",
            "context_length": 128000,
            "pricing": {"prompt": "0", "completion": "0"},
            "architecture": {"input_modalities": ["text", "image"]},
        },
        {
            "id": "anthropic/claude-sonnet-5.5",
            "name": "Anthropic: Claude Sonnet 5.5",
            "context_length": 1000000,
            "pricing": {"prompt": "0.000003", "completion": "0.000015"},
            "architecture": {"input_modalities": ["text"]},
        },
        {"id": "bad id with spaces", "name": "Broken"},
    ]
}


@pytest.fixture(autouse=True)
def secrets_key(monkeypatch):
    monkeypatch.setenv(secrets.ENV_NAME, Fernet.generate_key().decode())
    redact.clear_stored_cache()
    yield
    redact.clear_stored_cache()


def _add_provider(admin_client):
    return admin_client.post(
        reverse("studio:provider_add"),
        {
            "label": "OpenRouter",
            "name": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": KEY,
        },
    )


@pytest.fixture
def openrouter(admin_client):
    """OpenRouter added with a key; adding it reads its list, so its chat models are in the dropdowns."""
    with respx.mock(assert_all_called=False) as mock:
        route = mock.get("https://openrouter.ai/api/v1/models").mock(
            return_value=httpx.Response(200, json=OPENROUTER_MODELS)
        )
        _add_provider(admin_client)
        yield route


def test_openrouter_models_are_read_with_names_prices_and_vision(openrouter):
    models = remote_models.list_models(get_provider("openrouter"))
    assert [m.id for m in models] == ["anthropic/claude-sonnet-5.5", "meta-llama/llama-4-scout:free"]
    paid, free = models
    assert openrouter.calls.last.request.headers["Authorization"] == f"Bearer {KEY}"
    assert (free.status, free.context, free.vision, free.price) == ("free", 128000, True, "free")
    assert paid.status == "paid" and paid.price == "$3.00 in / $15.00 out per M tokens"
    assert paid.option_label == (
        "Anthropic: Claude Sonnet 5.5 (anthropic/claude-sonnet-5.5) · 1000k context · "
        "$3.00 in / $15.00 out per M tokens"
    )


@respx.mock
def test_ollama_lists_installed_models_and_gemini_ids_lose_their_prefix():
    respx.get("http://ollama.test:11434/api/tags").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "qwen3:27b"}, {"name": "gemma4:12b"}]})
    )
    ollama = ProviderSpec("ollama", "ollama_native", "http://ollama.test:11434")
    assert [(m.id, m.status) for m in remote_models.list_models(ollama)] == [
        ("gemma4:12b", "free"),
        ("qwen3:27b", "free"),
    ]
    respx.get("https://gemini.test/v1beta/openai/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "models/gemini-3.7-flash"}]})
    )
    gemini = ProviderSpec("gemini", "openai_compat", "https://gemini.test/v1beta/openai/")
    assert [(m.id, m.status) for m in remote_models.list_models(gemini)] == [("gemini-3.7-flash", "")]


@respx.mock
def test_listing_problems_are_explained():
    spec = ProviderSpec("x", "openai_compat", "https://x.test/v1", key_required=True)
    with pytest.raises(remote_models.RemoteModelsError, match="add the provider's key first"):
        remote_models.list_models(spec)
    respx.get("https://y.test/v1/models").mock(return_value=httpx.Response(401))
    with pytest.raises(remote_models.RemoteModelsError, match="refused the key"):
        remote_models.list_models(ProviderSpec("y", "openai_compat", "https://y.test/v1"))
    with pytest.raises(remote_models.RemoteModelsError, match="doesn't list"):
        remote_models.list_models(ProviderSpec("c", "cloudflare_images", "https://c.test"))


# ---- Automatic: a stored key puts the provider's models in the lists ----


def test_adding_a_provider_with_a_key_lists_its_models(admin_client, openrouter):
    rows = {row.model: row for row in AddedModel.objects.all()}
    assert set(rows) == {"anthropic/claude-sonnet-5.5", "meta-llama/llama-4-scout:free"}
    paid = rows["anthropic/claude-sonnet-5.5"]
    assert (paid.source, paid.status, paid.label) == ("listed", "paid", "Anthropic: Claude Sonnet 5.5")
    assert paid.details == "1000k context · $3.00 in / $15.00 out per M tokens"
    assert rows["meta-llama/llama-4-scout:free"].status == "free"
    assert ModelSync.objects.get(provider="openrouter").listed == 2
    # A key is the go-ahead: paid listed models are selectable everywhere models are chosen.
    assert catalog.by_key("openrouter::anthropic/claude-sonnet-5.5").selectable
    defaults = admin_client.get(reverse("studio:task_defaults"))
    assert "OpenRouter: 2 models" in defaults.text
    assert 'value="openrouter::anthropic/claude-sonnet-5.5"' in defaults.text
    providers = admin_client.get(reverse("studio:provider_keys"))
    assert "2 from its list" in providers.text and "Refresh model lists" in providers.text


def test_a_sync_follows_the_list_and_keeps_what_you_changed(admin_client, openrouter):
    AddedModel.objects.filter(model="meta-llama/llama-4-scout:free").update(hidden=True)
    AddedModel.objects.filter(model="anthropic/claude-sonnet-5.5").update(
        label="Claude (ours)", status="limited"
    )
    AddedModel.objects.create(provider="openrouter", model="x/by-hand", label="By hand")
    openrouter.mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    OPENROUTER_MODELS["data"][1],
                    {
                        "id": "google/gemini-9",
                        "name": "Google: Gemini 9",
                        "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    },
                    {"id": "openai/text-embedding-9", "name": "Embedding"},
                    {"id": "x/painter", "architecture": {"output_modalities": ["image"]}},
                ]
            },
        )
    )
    response = admin_client.post(
        reverse("studio:provider_keys"), {"action": "refresh", "provider": "openrouter"}
    )
    assert response.status_code == 302
    rows = {row.model: row for row in AddedModel.objects.all()}
    assert set(rows) == {
        "anthropic/claude-sonnet-5.5",
        "google/gemini-9",
        "x/by-hand",
    }  # gone, embedding, image
    assert (rows["anthropic/claude-sonnet-5.5"].label, rows["anthropic/claude-sonnet-5.5"].status) == (
        "Claude (ours)",
        "limited",
    )
    assert rows["x/by-hand"].source == "manual"


def test_a_failed_sync_is_shown_and_the_provider_still_appears(admin_client):
    with respx.mock(assert_all_called=False) as mock:
        mock.get("https://openrouter.ai/api/v1/models").mock(return_value=httpx.Response(503))
        response = _add_provider(admin_client)
        assert response.status_code == 302
        providers = admin_client.get(reverse("studio:provider_keys"))
    assert "the provider answered HTTP 503" in providers.text and "None yet" in providers.text
    assert "OpenRouter: <strong>none yet</strong>" in admin_client.get(reverse("studio:task_defaults")).text


def test_only_chat_models_are_listed():
    assert remote_models.is_chat("openai/gpt-5.5")
    for model_id in ("text-embedding-3-large", "whisper-large-v3", "meta-llama/llama-guard-4", "playai-tts"):
        assert not remote_models.is_chat(model_id), model_id


def test_stale_lists_are_found(openrouter):
    from datetime import timedelta

    from django.utils import timezone

    assert "openrouter" not in remote_models.stale()
    ModelSync.objects.filter(provider="openrouter").update(synced_at=timezone.now() - timedelta(hours=30))
    assert "openrouter" in remote_models.stale()


# ---- By hand: add several, rename, re-price, remove, restore ----


def test_the_picker_shows_the_models_in_the_lists_ticked(admin_client, openrouter):
    page = admin_client.get(reverse("studio:provider_model_add") + "?provider=openrouter")
    assert 'value="anthropic/claude-sonnet-5.5" checked' in page.text
    assert 'value="meta-llama/llama-4-scout:free" checked' in page.text
    assert "2 models from OpenRouter" in page.text and "Tick all shown" in page.text


def test_unticking_removes_and_ticking_restores(admin_client, openrouter):
    url = reverse("studio:provider_model_add")
    both = ["anthropic/claude-sonnet-5.5", "meta-llama/llama-4-scout:free"]
    admin_client.post(url, {"provider": "openrouter", "chosen": [both[1]], "shown": both})
    assert AddedModel.objects.get(model=both[0]).hidden  # listed: hidden, so a sync skips it
    page = admin_client.get(url + "?provider=openrouter")
    assert f'value="{both[0]}" >' in page.text or f'value="{both[0]}" checked' not in page.text
    admin_client.post(url, {"provider": "openrouter", "chosen": both, "shown": both})
    assert not AddedModel.objects.get(model=both[0]).hidden
    nothing = admin_client.post(url, {"provider": "openrouter", "chosen": both, "shown": both})
    assert "Nothing changed" in nothing.text


def test_several_models_are_added_at_once_and_a_hidden_one_is_restored(admin_client, openrouter):
    AddedModel.objects.filter(model="meta-llama/llama-4-scout:free").update(hidden=True)
    both = ["anthropic/claude-sonnet-5.5", "meta-llama/llama-4-scout:free"]
    response = admin_client.post(
        reverse("studio:provider_model_add"),
        {
            "provider": "openrouter",
            "chosen": both,
            "shown": both,
            "model": "x/one\nx/two\n",
            "unlisted_ok": "on",
            "status": "limited",
            "next": "another",
        },
    )
    assert response["Location"] == reverse("studio:provider_model_add") + "?provider=openrouter"
    assert not AddedModel.objects.get(model="meta-llama/llama-4-scout:free").hidden
    added = AddedModel.objects.filter(model__in=["x/one", "x/two"])
    assert sorted(added.values_list("model", "status", "source")) == [
        ("x/one", "limited", "manual"),
        ("x/two", "limited", "manual"),
    ]
    # Ids added by hand show up ticked too; unticking deletes them.
    page = admin_client.get(reverse("studio:provider_model_add") + "?provider=openrouter")
    assert 'value="x/one" checked' in page.text
    admin_client.post(
        reverse("studio:provider_model_add"),
        {"provider": "openrouter", "chosen": [*both, "x/two"], "shown": [*both, "x/one", "x/two"]},
    )
    assert not AddedModel.objects.filter(model="x/one").exists()


def test_an_id_the_provider_doesnt_list_is_refused_with_suggestions(admin_client, openrouter):
    url = reverse("studio:provider_model_add")
    refused = admin_client.post(url, {"provider": "openrouter", "model": "anthropic/claude-sonnet-55"})
    assert "Not in this provider&#x27;s list of models" in refused.text
    assert "did you mean anthropic/claude-sonnet-5.5?" in refused.text
    assert not AddedModel.objects.filter(model="anthropic/claude-sonnet-55").exists()


def test_a_typed_id_works_when_the_list_fails(admin_client, openrouter):
    openrouter.mock(return_value=httpx.Response(503))
    page = admin_client.get(reverse("studio:provider_model_add") + "?provider=openrouter&refresh=1")
    assert "list its models: the provider answered HTTP 503" in page.text  # "Couldn't" is escaped
    response = admin_client.post(
        reverse("studio:provider_model_add"),
        {"provider": "openrouter", "model": "openai/gpt-5.5", "label": "GPT"},
    )
    assert response.status_code == 302
    item = AddedModel.objects.get(model="openai/gpt-5.5")
    assert (item.label, item.status, item.source) == ("GPT", "paid", "manual")
    empty = admin_client.post(reverse("studio:provider_model_add"), {"provider": "openrouter"})
    assert "Nothing changed" in empty.text


def test_an_unpriced_model_takes_the_providers_usual_status():
    from apps.ai.forms import AddedModelForm

    assert catalog.usual_status("groq") in ("free", "limited")
    assert catalog.usual_status("an-added-provider") == "paid"
    form = AddedModelForm(
        {"provider": "groq", "chosen": ["llama-4-scout"], "shown": ["llama-4-scout"]},
        provider_choices=[("groq", "Groq")],
        remote=[remote_models.RemoteModel(id="llama-4-scout", name="Llama 4 Scout")],
        default_status=catalog.usual_status("groq"),
    )
    assert form.is_valid(), form.errors
    added, removed = form.save()
    assert (added[0].status, removed) == (catalog.usual_status("groq"), 0)
    assert "when it doesn&#x27;t say" in str(form["status"])


def test_models_are_renamed_repriced_removed_and_restored_in_bulk(admin_client, openrouter):
    manual = AddedModel.objects.create(provider="openrouter", model="x/by-hand", label="By hand")
    listed = AddedModel.objects.get(model="anthropic/claude-sonnet-5.5")
    url = reverse("studio:provider_models")
    page = admin_client.get(url + "?provider=openrouter&q=claude")
    assert "Anthropic: Claude Sonnet 5.5" in page.text and "Llama 4 Scout" not in page.text
    admin_client.post(
        url,
        {
            "provider": "openrouter",
            "action": "save",
            "row": [listed.pk, manual.pk],
            f"label-{listed.pk}": "Claude",
            f"status-{listed.pk}": "limited",
            f"label-{manual.pk}": "By hand",
            f"status-{manual.pk}": "paid",
        },
    )
    listed.refresh_from_db()
    assert (listed.label, listed.status) == ("Claude", "limited")
    admin_client.post(url, {"provider": "openrouter", "action": "remove", "pick": [listed.pk, manual.pk]})
    assert not AddedModel.objects.filter(pk=manual.pk).exists()  # by hand: deleted
    listed.refresh_from_db()
    assert listed.hidden and catalog.by_key("openrouter::anthropic/claude-sonnet-5.5") is None
    assert "Claude" in admin_client.get(url + "?provider=openrouter&hidden=1").text
    admin_client.post(
        url, {"provider": "openrouter", "hidden": "1", "action": "restore", "pick": [listed.pk]}
    )
    listed.refresh_from_db()
    assert not listed.hidden


def test_default_models_links_back_from_adding(admin_client, openrouter):
    defaults_url = reverse("studio:task_defaults")
    assert "?provider=openrouter&amp;return_to=defaults" in admin_client.get(defaults_url).text
    response = admin_client.post(
        reverse("studio:provider_model_add"),
        {"provider": "openrouter", "model": "x/new", "unlisted_ok": "on", "return_to": "defaults"},
    )
    assert response["Location"] == defaults_url
