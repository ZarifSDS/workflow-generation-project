"""Model prices, context windows and the usage ledger (apps/ai/pricing.py, apps/ai/usage.py,
apps/studio/estimates.py; docs/pricing-and-ux-plan.md)."""

from decimal import Decimal

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from django.urls import reverse

from apps.ai import pricing, redact, secrets, usage
from apps.ai.models import AddedModel, ModelInfo, PriceReference, ProviderConfig, UsageRecord
from apps.ai.remote_models import RemoteModel, _openai_entry
from apps.ai.types import GenerationResult

pytestmark = pytest.mark.django_db

REFERENCE_URL = "https://prices.test/model_prices.json"
REFERENCE = {
    "sample_spec": {"input_cost_per_token": 1},
    "groq/openai/gpt-oss-120b": {
        "litellm_provider": "groq",
        "mode": "chat",
        "input_cost_per_token": 1.5e-07,
        "output_cost_per_token": 6e-07,
        "max_input_tokens": 131072,
        "max_output_tokens": 32766,
    },
    "gemini/gemini-3.7-flash": {
        "litellm_provider": "gemini",
        "mode": "chat",
        "input_cost_per_token": 3e-07,
        "output_cost_per_token": 2.5e-06,
        "cache_read_input_token_cost": 7.5e-08,
        "max_input_tokens": 1048576,
        "max_output_tokens": 65535,
    },
    "ollama/kimi-k3": {"litellm_provider": "ollama", "mode": "chat", "max_input_tokens": 262144},
    "text-embedding-9": {"litellm_provider": "openai", "mode": "embedding", "input_cost_per_token": 1e-08},
}


@pytest.fixture(autouse=True)
def fresh():
    pricing.clear_cache()
    yield
    pricing.clear_cache()


def _reference():
    PriceReference.objects.create(url=REFERENCE_URL, entries=pricing.parse_reference(REFERENCE))


# ---- Reading the sources ----


def test_openrouter_prices_and_limits_are_kept_as_numbers():
    model = _openai_entry(
        {
            "id": "openai/gpt-luna",
            "context_length": 1050000,
            "top_provider": {"max_completion_tokens": 128000},
            "pricing": {"prompt": "0.0000001", "completion": "0.0000005", "input_cache_read": "0.00000001"},
        }
    )
    assert (model.input_per_m, model.output_per_m) == pytest.approx((0.1, 0.5))
    assert model.cached_input_per_m == pytest.approx(0.01)
    assert (model.context, model.max_output) == (1050000, 128000)
    # Per-million numbers (some OpenAI-compatible hosts) and OpenRouter's "-1" (variable: unknown).
    host = _openai_entry({"id": "m", "pricing": {"input": 0.2, "output": 0.6}})
    assert (host.input_per_m, host.output_per_m) == (0.2, 0.6)
    router = _openai_entry({"id": "openrouter/auto", "pricing": {"prompt": "-1", "completion": "-1"}})
    assert (router.input_per_m, router.price, router.free) == (None, "", None)


def test_the_reference_list_keeps_chat_models_and_matches_by_provider():
    entries = pricing.parse_reference(REFERENCE)
    assert set(entries) == {"groq/openai/gpt-oss-120b", "gemini/gemini-3.7-flash", "ollama/kimi-k3"}
    entry, note = pricing.match_reference("groq", "openai/gpt-oss-120b", entries)
    assert entry["in"] == 1.5e-07 and note == "reference list: groq/openai/gpt-oss-120b"
    entry, _ = pricing.match_reference("gemini", "models/gemini-3.7-flash-latest", entries)
    assert entry["context"] == 1048576  # "models/" and "-latest" are tolerated
    assert pricing.match_reference("openrouter", "nobody/knows", entries) == (None, "")
    # A model only another host lists lends its context window, never its price.
    entry, note = pricing.match_reference("ollama_cloud", "kimi-k3", entries)
    assert entry["context"] == 262144 and entry["in"] is None


@respx.mock
def test_the_reference_list_is_read_weekly_and_a_failure_is_kept(settings):
    settings.AI_PRICE_REFERENCE_URL = REFERENCE_URL
    route = respx.get(REFERENCE_URL).mock(return_value=httpx.Response(200, json=REFERENCE))
    row = pricing.refresh_reference()
    assert len(row.entries) == 3 and not row.error
    pricing.refresh_reference()
    assert route.call_count == 1  # read at most once a week
    route.mock(return_value=httpx.Response(500))
    row = pricing.refresh_reference(force=True)
    assert "couldn't read the reference list" in row.error and len(row.entries) == 3  # old list kept


# ---- Resolving: hand-entered, then the provider, then the reference list ----


def test_values_come_from_the_first_source_that_has_them():
    _reference()
    listed = RemoteModel(id="openai/gpt-oss-120b", context=131072, input_per_m=0.2, output_per_m=0.7)
    pricing.update("groq", listed=[listed])
    info = ModelInfo.objects.get(provider="groq", model="openai/gpt-oss-120b")
    assert (info.input_per_m, info.price_source, info.context_source) == (
        Decimal("0.2"),
        "provider",
        "provider",
    )
    # A pass without the provider's listing keeps what the provider said.
    pricing.update("groq", model_ids=["openai/gpt-oss-120b"])
    info.refresh_from_db()
    assert info.input_per_m == Decimal("0.2")
    # Without a provider price, the reference list fills in, with its source and match noted.
    pricing.update("gemini", model_ids=["gemini-3.7-flash"])
    gemini = ModelInfo.objects.get(provider="gemini")
    assert (gemini.input_per_m, gemini.output_per_m, gemini.cached_input_per_m) == (
        Decimal("0.3"),
        Decimal("2.5"),
        Decimal("0.075"),
    )
    assert gemini.price_source == "reference" and "gemini/gemini-3.7-flash" in gemini.note
    # A value typed by hand is never overwritten.
    gemini.input_per_m, gemini.price_source = Decimal("9"), "manual"
    gemini.save()
    pricing.update("gemini", model_ids=["gemini-3.7-flash"])
    gemini.refresh_from_db()
    assert gemini.input_per_m == Decimal("9")
    # Unknown stays unknown; local models are free.
    pricing.update("openrouter", model_ids=["nobody/knows"])
    assert ModelInfo.objects.get(model="nobody/knows").input_per_m is None
    pricing.update("ollama", listed=[RemoteModel(id="qwen3:27b", context=32768)])
    local = ModelInfo.objects.get(provider="ollama")
    assert (local.input_per_m, local.context_window) == (Decimal("0"), 32768)


def test_a_problem_while_pricing_never_breaks_the_caller(monkeypatch):
    monkeypatch.setattr(pricing, "_reference_entries", lambda: 1 / 0)
    assert pricing.update("groq", model_ids=["x"]) == 0


# ---- What the lists say, and what a call costs ----


def test_option_facts_say_the_price_the_way_the_key_is_billed():
    ModelInfo.objects.create(
        provider="openrouter",
        model="m",
        input_per_m=Decimal("0.1"),
        output_per_m=Decimal("0.5"),
        context_window=1050000,
    )
    ModelInfo.objects.create(
        provider="groq",
        model="g",
        input_per_m=Decimal("0.15"),
        output_per_m=Decimal("0.6"),
        context_window=131072,
    )
    assert pricing.facts("openrouter", "m") == "$0.10 / $0.50 per M · 1,050k context"
    assert pricing.facts("groq", "g") == "free tier (list $0.15 / $0.60 per M) · 131k context"
    assert pricing.facts("ollama_cloud", "nope") == "on your plan"
    assert pricing.facts("ollama", "q") == "free: your machine"
    assert pricing.facts("openrouter", "unknown") == "price unknown"
    ProviderConfig.objects.create(name="groq", label="Groq", billing="per_token")
    pricing.clear_cache()
    assert pricing.facts("groq", "g").startswith("$0.15 / $0.60 per M")


def test_cost_is_billed_estimated_free_or_unknown():
    ModelInfo.objects.create(
        provider="openrouter", model="m", input_per_m=Decimal("2"), output_per_m=Decimal("10")
    )
    assert pricing.cost("openrouter", "m", 1000, 500, billed=0.0123) == (Decimal("0.0123"), "billed")
    assert pricing.cost("openrouter", "m", 1000, 500) == (Decimal("0.007000"), "estimated")
    assert pricing.cost("groq", "m", 1000, 500) == (Decimal("0"), "free")
    assert pricing.cost("openrouter", "other", 1000, 500) == (None, "unknown")


# ---- The ledger ----


def _result(**extra):
    return GenerationResult(
        provider="openrouter", model="m", text="x", input_tokens=1000, output_tokens=500, **extra
    )


def test_calls_are_recorded_with_what_they_belong_to():
    ModelInfo.objects.create(
        provider="openrouter", model="m", input_per_m=Decimal("2"), output_per_m=Decimal("10")
    )
    with usage.scope("step", run_id=7, step_key="draft", object_id=3):
        usage.record(_result())
        usage.record(_result(stats={"billed_cost": 0.01}))
    usage.record(_result())
    rows = list(UsageRecord.objects.order_by("pk"))
    assert [(r.kind, r.run_id, r.step_key, r.cost_kind) for r in rows] == [
        ("step", 7, "draft", "estimated"),
        ("step", 7, "draft", "billed"),
        ("other", None, "", "estimated"),
    ]
    steps, total = usage.for_run(7)
    assert steps["draft"]["calls"] == 2 and total["cost"] == Decimal("0.017") and not total["exact"]


def test_a_ledger_failure_never_fails_the_call(monkeypatch):
    def broken(**kwargs):
        raise RuntimeError("database gone")

    monkeypatch.setattr(UsageRecord.objects, "create", broken)
    assert usage.record(_result()) is None


def test_openrouter_billed_cost_is_read_from_the_stream(settings, monkeypatch):
    import json

    import httpx2
    import openai

    from apps.ai.adapters import openai_compat
    from apps.ai.service import generate

    settings.AI_PROVIDERS = {"compat": {"adapter": "openai_compat", "base_url": "https://llm.test/v1"}}
    chunks = [
        {"id": "1", "object": "chat.completion.chunk", "created": 0, "model": "m",
         "choices": [{"index": 0, "delta": {"content": "hi"}, "finish_reason": None}]},
        {"id": "1", "object": "chat.completion.chunk", "created": 0, "model": "m", "choices": [],
         "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12, "cost": 0.00042}},
    ]  # fmt: skip
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
    monkeypatch.setattr(
        openai_compat,
        "http_client_factory",
        lambda: openai.DefaultHttpxClient(
            transport=httpx2.MockTransport(
                lambda request: httpx2.Response(
                    200, content=body.encode(), headers={"content-type": "text/event-stream"}
                )
            )
        ),
    )
    result = generate("compat", "m", [{"role": "user", "content": "x"}])
    assert result.stats["billed_cost"] == pytest.approx(0.00042)
    row = UsageRecord.objects.get()
    assert (row.input_tokens, row.output_tokens, row.cost_kind) == (10, 2, "billed")


# ---- Estimates and the context guard ----


def test_a_run_estimate_adds_up_priced_steps_and_names_the_unknown():
    from apps.studio import estimates

    ModelInfo.objects.create(
        provider="openrouter",
        model="m",
        input_per_m=Decimal("1"),
        output_per_m=Decimal("4"),
        context_window=8000,
    )
    found = estimates.run_estimate(
        [
            {"step": "research", "provider": "openrouter", "model": "m"},
            {"step": "outline", "provider": "groq", "model": "openai/gpt-oss-120b"},
            {"step": "draft", "provider": "openrouter", "model": "unpriced"},
        ],
        seconds_for=lambda step, provider, model: 30,
    )
    research_in, research_out, _ = estimates.DEFAULT_TOKENS["research"]
    assert found["cost"] == (Decimal(research_in) * 1 + Decimal(research_out) * 4) / 1_000_000
    assert found["paid"] == ["openrouter::m"] and found["unknown"] == ["openrouter::unpriced"]
    assert found["seconds"] == 90 and found["too_small"] == ["research"]  # 8k context < ~15k needed


# ---- The settings pages ----


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setenv(secrets.ENV_NAME, Fernet.generate_key().decode())
    redact.clear_stored_cache()


def test_billing_is_chosen_per_key_on_ai_providers(admin_client, keys):
    page = admin_client.get(reverse("studio:provider_keys"))
    assert "Billed as" in page.text and "Usual for Groq: free tier" in page.text
    response = admin_client.post(
        reverse("studio:provider_keys"), {"action": "billing", "billing-groq": "per_token"}
    )
    assert response.status_code == 302
    assert ProviderConfig.objects.get(name="groq").billing == "per_token"
    assert pricing.billing("groq") == "per_token"


def test_prices_typed_on_manage_models_stick_and_clearing_hands_back(admin_client, keys):
    row = AddedModel.objects.create(provider="openrouter", model="x/m", label="M", source="listed")
    ModelInfo.objects.create(
        provider="openrouter",
        model="x/m",
        input_per_m=Decimal("1"),
        output_per_m=Decimal("2"),
        price_source="provider",
    )
    url = reverse("studio:provider_models")
    assert 'value="1"' in admin_client.get(url).text
    post = {"action": "save", "row": row.pk, f"label-{row.pk}": "M", f"status-{row.pk}": "paid"}
    admin_client.post(url, {**post, f"in-{row.pk}": "0.5", f"out-{row.pk}": "$1.25", f"ctx-{row.pk}": "128k"})
    info = ModelInfo.objects.get(model="x/m")
    assert (info.input_per_m, info.output_per_m, info.price_source) == (
        Decimal("0.5"),
        Decimal("1.25"),
        "manual",
    )
    assert (info.context_window, info.context_source) == (128000, "manual")
    # A sync leaves hand-entered values alone.
    pricing.update("openrouter", listed=[RemoteModel(id="x/m", input_per_m=3, output_per_m=4, context=9)])
    info.refresh_from_db()
    assert (info.input_per_m, info.context_window) == (Decimal("0.5"), 128000)
    admin_client.post(url, {**post, f"in-{row.pk}": "", f"out-{row.pk}": "", f"ctx-{row.pk}": ""})
    info.refresh_from_db()
    assert (info.input_per_m, info.price_source, info.context_source) == (None, "", "")


def test_usage_page_lists_months_and_runs(admin_client, keys):
    UsageRecord.objects.create(provider="openrouter", model="m", input_tokens=10, output_tokens=5,
                               cost=Decimal("0.25"), cost_kind="billed")  # fmt: skip
    page = admin_client.get(reverse("studio:usage"))
    assert page.status_code == 200 and "$0.25" in page.text and "billed" in page.text


def test_the_wizard_shows_prices_and_carries_the_estimate_data(admin_client):
    ModelInfo.objects.create(provider="ollama_cloud", model="gpt-oss:120b", context_window=131072)
    page = admin_client.get(reverse("studio:brief_new"))
    assert "data-run-estimate" in page.text and 'data-step-in="' in page.text
    assert "on your plan · 131k context" in page.text  # Ollama Cloud: a subscription
    assert 'data-in="0" data-out="0"' in page.text
