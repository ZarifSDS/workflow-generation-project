"""OpenAI-compatible chat adapter (Gemini, Groq, Ollama Cloud) using the openai SDK with streaming."""

import time

import openai

from ..types import GenerationResult, ProviderError


def _classify(error):
    if isinstance(error, openai.RateLimitError):
        return ProviderError("rate_limited", str(error), 429)
    if isinstance(error, openai.AuthenticationError):
        return ProviderError("auth", str(error), 401)
    if isinstance(error, openai.APIStatusError):
        status = error.status_code
        if status == 402:
            return ProviderError("not_free", "Model is not included in the free plan", status)
        if status == 403:
            return ProviderError("unavailable", str(error), status)
        if status >= 500:
            return ProviderError("server", str(error), status)
        return ProviderError("bad_request", str(error), status)
    if isinstance(error, (openai.APIConnectionError, openai.APITimeoutError)):
        return ProviderError("network", str(error))
    return ProviderError("unknown", str(error))


# Tests set this to a callable returning an openai.DefaultHttpxClient with a mock transport.
# (The openai SDK bundles its own httpx fork, `httpx2`, which respx doesn't intercept.)
http_client_factory = None


def chat(spec, model, messages, options):
    client = openai.OpenAI(
        base_url=spec.base_url,
        api_key=spec.api_key or "unused",
        default_headers=spec.headers,
        timeout=options.get("timeout", 600),
        max_retries=0,  # retries are handled by apps.ai.service
        http_client=http_client_factory() if http_client_factory else None,
    )
    params = {"model": model, "messages": messages, "stream": True}
    if "temperature" in options:
        params["temperature"] = options["temperature"]
    if "max_tokens" in options:
        params["max_tokens"] = options["max_tokens"]
    if options.get("include_usage", True):
        params["stream_options"] = {"include_usage": True}

    started = time.monotonic()
    first_token_at = None
    parts, usage = [], None
    try:
        for chunk in client.chat.completions.create(**params):
            if chunk.usage:
                usage = chunk.usage
            for choice in chunk.choices or []:
                content = choice.delta.content if choice.delta else None
                if content:
                    if first_token_at is None:
                        first_token_at = time.monotonic()
                    parts.append(content)
    except openai.OpenAIError as error:
        raise _classify(error) from error

    total = time.monotonic() - started
    output_tokens = usage.completion_tokens if usage else None
    generation_time = total - (first_token_at - started) if first_token_at else None
    return GenerationResult(
        provider=spec.name,
        model=model,
        text="".join(parts),
        input_tokens=usage.prompt_tokens if usage else None,
        output_tokens=output_tokens,
        time_to_first_token=(first_token_at - started) if first_token_at else None,
        total_time=total,
        # Speed is meaningless for a handful of tokens (they often arrive in one chunk).
        tokens_per_second=(
            output_tokens / generation_time
            if output_tokens and output_tokens >= 50 and generation_time
            else None
        ),
    )
