"""Add a model by picking it from the provider's own list (apps/ai/remote_models.py)."""

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from django.urls import reverse

from apps.ai import redact, remote_models, secrets
from apps.ai.models import AddedModel
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


@pytest.fixture
def openrouter(admin_client):
    with respx.mock(assert_all_called=False) as mock:
        admin_client.post(
            reverse("studio:provider_add"),
            {
                "label": "OpenRouter",
                "name": "openrouter",
                "base_url": "https://openrouter.ai/api/v1",
                "api_key": KEY,
            },
        )
        route = mock.get("https://openrouter.ai/api/v1/models").mock(
            return_value=httpx.Response(200, json=OPENROUTER_MODELS)
        )
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


def test_the_add_page_offers_the_providers_models(admin_client, openrouter):
    page = admin_client.get(reverse("studio:provider_model_add") + "?provider=openrouter")
    assert page.status_code == 200
    assert '<optgroup label="Free">' in page.text and '<optgroup label="Paid">' in page.text
    assert "Meta: Llama 4 Scout (free)" in page.text and "2 models from OpenRouter" in page.text
    assert "Or type a model id" in page.text


def test_a_picked_model_is_added_with_its_name_and_status(admin_client, openrouter):
    response = admin_client.post(
        reverse("studio:provider_model_add"),
        {"provider": "openrouter", "listed": "meta-llama/llama-4-scout:free", "next": "another"},
    )
    assert response["Location"] == reverse("studio:provider_model_add") + "?provider=openrouter"
    item = AddedModel.objects.get()
    assert (item.model, item.label, item.status) == (
        "meta-llama/llama-4-scout:free",
        "Meta: Llama 4 Scout (free)",
        "free",
    )
    again = admin_client.get(reverse("studio:provider_model_add") + "?provider=openrouter")
    assert "already added" in again.text
    duplicate = admin_client.post(
        reverse("studio:provider_model_add"),
        {"provider": "openrouter", "listed": "meta-llama/llama-4-scout:free"},
    )
    assert "already added for this provider" in duplicate.text and AddedModel.objects.count() == 1


def test_a_typed_id_still_works_when_the_list_fails(admin_client, openrouter):
    openrouter.mock(return_value=httpx.Response(503))
    page = admin_client.get(reverse("studio:provider_model_add") + "?provider=openrouter&refresh=1")
    assert "list its models: the provider answered HTTP 503" in page.text  # "Couldn't" is escaped
    response = admin_client.post(
        reverse("studio:provider_model_add"), {"provider": "openrouter", "model": "openai/gpt-5.5"}
    )
    assert response.status_code == 302
    item = AddedModel.objects.get()
    assert (item.model, item.label, item.status) == ("openai/gpt-5.5", "openai/gpt-5.5", "paid")
    empty = admin_client.post(reverse("studio:provider_model_add"), {"provider": "openrouter"})
    assert "Pick a model from the list, or type its id." in empty.text


def test_an_unpriced_model_takes_the_providers_usual_status():
    from apps.ai import catalog
    from apps.ai.forms import AddedModelForm

    assert catalog.usual_status("groq") in ("free", "limited")
    assert catalog.usual_status("an-added-provider") == "paid"
    listed = remote_models.RemoteModel(id="llama-4-scout", name="Llama 4 Scout")
    form = AddedModelForm(
        {"provider": "groq", "listed": "llama-4-scout"},
        provider_choices=[("groq", "Groq")],
        remote=[listed],
        default_status=catalog.usual_status("groq"),
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["status"] == catalog.usual_status("groq")
    assert "when it doesn&#x27;t say" in str(form["status"])
