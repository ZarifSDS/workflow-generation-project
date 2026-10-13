"""Local Ollama via its native /api/chat endpoint.

Used instead of Ollama's OpenAI-compatible endpoint because that one ignores num_ctx, keep_alive
and think, and doesn't report eval_count/eval_duration (true generation speed). See ADR 0003.
"""

import json
import time

import httpx

from ..types import GenerationResult, ProviderError

NANOSECONDS = 1_000_000_000


def _post_stream(spec, payload, timeout):
    parts, final, first_token_at = [], {}, None
    started = time.monotonic()
    with (
        httpx.Client(base_url=spec.base_url, headers=spec.headers, timeout=timeout) as client,
        client.stream("POST", "/api/chat", json=payload) as response,
    ):
        if response.status_code >= 400:
            body = response.read().decode(errors="replace")
            kind = "server" if response.status_code >= 500 else "bad_request"
            raise ProviderError(kind, f"Ollama {response.status_code}: {body[:300]}", response.status_code)
        for line in response.iter_lines():
            if not line:
                continue
            data = json.loads(line)
            if data.get("error"):
                raise ProviderError("bad_request", f"Ollama: {data['error']}")
            content = (data.get("message") or {}).get("content")
            if content:
                if first_token_at is None:
                    first_token_at = time.monotonic()
                parts.append(content)
            if data.get("done"):
                final = data
    return "".join(parts), final, started, first_token_at


def _memory_split(spec, model):
    """GPU vs total memory for the loaded model, from /api/ps (bytes)."""
    try:
        with httpx.Client(base_url=spec.base_url, headers=spec.headers, timeout=10) as client:
            for loaded in client.get("/api/ps").json().get("models", []):
                if loaded.get("name") == model or loaded.get("model") == model:
                    size, vram = loaded.get("size", 0), loaded.get("size_vram", 0)
                    return {
                        "model_bytes": size,
                        "vram_bytes": vram,
                        "gpu_share": round(vram / size, 3) if size else None,
                    }
    except (httpx.HTTPError, ValueError):
        pass
    return {}


def _native_message(message):
    """OpenAI-style list content ([{"type": "text"}, {"type": "image_url"}]) -> content + images."""
    content = message.get("content")
    if not isinstance(content, list):
        return message
    texts, images = [], []
    for part in content:
        if part.get("type") == "text":
            texts.append(part.get("text", ""))
        elif part.get("type") == "image_url":
            url = part.get("image_url", {}).get("url", "")
            if not url.startswith("data:"):
                raise ProviderError("bad_request", "Ollama needs images as base64 data URLs")
            images.append(url.partition(",")[2])
    native = {**message, "content": "\n\n".join(texts)}
    if images:
        native["images"] = images
    return native


def chat(spec, model, messages, options):
    messages = [_native_message(message) for message in messages]
    payload = {"model": model, "messages": messages, "stream": True, "options": {}}
    for key in ("num_ctx", "temperature", "num_predict", "top_p"):
        if key in options:
            payload["options"][key] = options[key]
    if "max_tokens" in options and "num_predict" not in options:
        payload["options"]["num_predict"] = options["max_tokens"]
    if "keep_alive" in options:
        payload["keep_alive"] = options["keep_alive"]
    if "think" in options:
        payload["think"] = options["think"]

    timeout = httpx.Timeout(connect=10, read=options.get("timeout", 900), write=60, pool=10)
    try:
        try:
            text, final, started, first_token_at = _post_stream(spec, payload, timeout)
        except ProviderError as error:
            # Models without a thinking mode reject `think`; retry once without it.
            if "think" in payload and "think" in str(error).lower():
                payload.pop("think")
                text, final, started, first_token_at = _post_stream(spec, payload, timeout)
            else:
                raise
    except httpx.TimeoutException as error:
        raise ProviderError("network", f"Ollama timed out: {error}") from error
    except httpx.TransportError as error:
        raise ProviderError("network", f"Cannot reach Ollama at {spec.base_url}: {error}") from error

    total = time.monotonic() - started
    eval_count, eval_duration = final.get("eval_count"), final.get("eval_duration")
    stats = {
        "load_seconds": final.get("load_duration", 0) / NANOSECONDS,
        "prompt_eval_seconds": final.get("prompt_eval_duration", 0) / NANOSECONDS,
        **_memory_split(spec, model),
    }
    return GenerationResult(
        provider=spec.name,
        model=model,
        text=text,
        input_tokens=final.get("prompt_eval_count"),
        output_tokens=eval_count,
        time_to_first_token=(first_token_at - started) if first_token_at else None,
        total_time=total,
        tokens_per_second=(eval_count / (eval_duration / NANOSECONDS))
        if eval_count and eval_duration
        else None,
        stats=stats,
    )
