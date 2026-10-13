import base64
import json

import httpx
import httpx2
import openai
import pytest
import respx

from apps.ai.adapters import openai_compat
from apps.ai.providers import get_provider
from apps.ai.service import generate, generate_image
from apps.ai.types import ProviderError

OPENAI_BASE = "https://llm.test/v1"
OLLAMA_BASE = "http://ollama.test:11434"
CF_BASE = "https://cf.test/client/v4"


@pytest.fixture(autouse=True)
def providers(settings, monkeypatch):
    settings.AI_PROVIDERS = {
        "compat": {"adapter": "openai_compat", "base_url": OPENAI_BASE, "api_key_env": "TEST_KEY"},
        "ollama": {"adapter": "ollama_native", "base_url": OLLAMA_BASE},
        "cf": {
            "adapter": "cloudflare_images",
            "base_url": CF_BASE,
            "api_key_env": "CF_TOKEN",
            "account_env": "CF_ACCOUNT",
        },
    }
    settings.AI_RETRY_BACKOFF = 0
    monkeypatch.setenv("TEST_KEY", "k")
    monkeypatch.setenv("CF_TOKEN", "t")
    monkeypatch.setenv("CF_ACCOUNT", "acc")


class FakeOpenAIServer:
    """Serves queued responses to the openai SDK through an httpx2 mock transport."""

    def __init__(self, monkeypatch):
        self.responses, self.requests = [], []
        monkeypatch.setattr(
            openai_compat,
            "http_client_factory",
            lambda: openai.DefaultHttpxClient(transport=httpx2.MockTransport(self._handle)),
        )

    def _handle(self, request):
        self.requests.append(request)
        status, body, headers = self.responses.pop(0)
        return httpx2.Response(status, content=body.encode(), headers=headers)

    def queue_stream(self, *chunks):
        body = "".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        self.responses.append((200, body, {"content-type": "text/event-stream"}))

    def queue_error(self, status, message):
        body = json.dumps({"error": {"message": message}})
        self.responses.append((status, body, {"content-type": "application/json"}))


@pytest.fixture
def fake_openai(monkeypatch):
    return FakeOpenAIServer(monkeypatch)


def delta(text):
    return {
        "id": "1",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "m",
        "choices": [{"index": 0, "delta": {"content": text}, "finish_reason": None}],
    }


USAGE = {
    "id": "1",
    "object": "chat.completion.chunk",
    "created": 0,
    "model": "m",
    "choices": [],
    "usage": {"prompt_tokens": 12, "completion_tokens": 60, "total_tokens": 72},
}
MESSAGES = [{"role": "user", "content": "hi"}]


def test_missing_key_is_not_configured(monkeypatch):
    monkeypatch.delenv("TEST_KEY")
    with pytest.raises(ProviderError) as error:
        get_provider("compat")
    assert error.value.kind == "not_configured"


def test_openai_compat_streams_text_and_usage(fake_openai):
    fake_openai.queue_stream(delta("Hel"), delta("lo"), USAGE)
    result = generate("compat", "m", MESSAGES, {"max_tokens": 100})
    assert result.text == "Hello"
    assert (result.input_tokens, result.output_tokens) == (12, 60)
    request = fake_openai.requests[-1]
    assert str(request.url) == f"{OPENAI_BASE}/chat/completions"
    assert request.headers["user-agent"].startswith("workflow-studio")


def test_payment_required_is_not_free_and_not_retried(fake_openai):
    fake_openai.queue_error(402, "not included in your free usage")
    with pytest.raises(ProviderError) as error:
        generate("compat", "m", MESSAGES)
    assert error.value.kind == "not_free"
    assert len(fake_openai.requests) == 1


def test_server_errors_are_retried_then_succeed(fake_openai):
    fake_openai.queue_error(503, "busy")
    fake_openai.queue_stream(delta("ok"), USAGE)
    result = generate("compat", "m", MESSAGES, retries=2)
    assert result.text == "ok"
    assert result.attempts == 2
    assert len(fake_openai.requests) == 2


@respx.mock
def test_ollama_native_reports_speed_and_memory_split():
    lines = [
        {"message": {"content": "Hi "}, "done": False},
        {"message": {"content": "there"}, "done": False},
        {"done": True, "eval_count": 100, "eval_duration": 4_000_000_000, "prompt_eval_count": 20},
    ]
    chat = respx.post(f"{OLLAMA_BASE}/api/chat").mock(
        return_value=httpx.Response(200, text="\n".join(json.dumps(line) for line in lines))
    )
    respx.get(f"{OLLAMA_BASE}/api/ps").mock(
        return_value=httpx.Response(200, json={"models": [{"name": "q", "size": 100, "size_vram": 40}]})
    )
    result = generate("ollama", "q", MESSAGES, {"num_ctx": 8192, "think": True, "max_tokens": 50})
    sent = json.loads(chat.calls.last.request.content)
    assert result.text == "Hi there"
    assert result.tokens_per_second == 25.0
    assert result.stats["gpu_share"] == 0.4
    assert sent["options"] == {"num_ctx": 8192, "num_predict": 50}
    assert sent["think"] is True


@respx.mock
def test_ollama_retries_without_think_when_unsupported():
    chat = respx.post(f"{OLLAMA_BASE}/api/chat").mock(
        side_effect=[
            httpx.Response(400, json={"error": "model does not support thinking"}),
            httpx.Response(200, text=json.dumps({"message": {"content": "ok"}, "done": True})),
        ]
    )
    respx.get(f"{OLLAMA_BASE}/api/ps").mock(return_value=httpx.Response(200, json={"models": []}))
    result = generate("ollama", "q", MESSAGES, {"think": True})
    assert result.text == "ok"
    assert "think" not in json.loads(chat.calls.last.request.content)


@respx.mock
def test_cloudflare_uses_multipart_for_flux2_and_json_for_schnell():
    png = b"\x89PNG\r\n\x1a\nrest"
    payload = {"result": {"image": base64.b64encode(png).decode()}, "success": True}
    klein = respx.post(f"{CF_BASE}/accounts/acc/ai/run/@cf/black-forest-labs/flux-2-klein-4b").mock(
        return_value=httpx.Response(200, json=payload)
    )
    schnell = respx.post(f"{CF_BASE}/accounts/acc/ai/run/@cf/black-forest-labs/flux-1-schnell").mock(
        return_value=httpx.Response(200, json=payload)
    )
    image = generate_image(
        "cf", "@cf/black-forest-labs/flux-2-klein-4b", "a lab", {"width": 512, "height": 512}
    )
    assert image.mime_type == "image/png" and image.data == png
    assert klein.calls.last.request.headers["content-type"].startswith("multipart/form-data")

    generate_image("cf", "@cf/black-forest-labs/flux-1-schnell", "a lab", {"width": 512, "steps": 4})
    sent = json.loads(schnell.calls.last.request.content)
    assert sent == {"prompt": "a lab", "steps": 4}  # width is not accepted by schnell
