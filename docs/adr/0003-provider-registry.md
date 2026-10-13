# ADR 0003: Provider registry with one OpenAI-compatible client

- Status: Accepted (implementation in M2)
- Date: 2026-10-13

## Context

There is no paid Claude/OpenAI API. Candidates are local Ollama models (host GPU 8 GB + 64 GB RAM) and free API tiers whose limits and terms change often. Leaderboard-based model picks have proven unreliable, so the model choice must stay swappable and be decided by evaluating real briefs.

## Decision

- All **text** providers are called through the `openai` Python SDK, varying only `base_url`, API key and model. Ollama, Ollama Cloud, Gemini, Mistral, NVIDIA NIM, Groq and OpenRouter all expose OpenAI-compatible endpoints.
- **Image** providers implement a small interface with two backends: ComfyUI (HTTP API, local) and Cloudflare Workers AI (REST).
- Pipeline steps reference a **profile** (`quality`, `fast`, `image`). Profiles map to a provider, a model and options (`num_ctx`, `keep_alive`, `think`) in admin-editable settings. Each profile can have a fallback provider.
- API keys come only from environment variables and are never stored in the database or logged.

## Consequences

- Adding a provider is configuration plus, at most, a small adapter.
- Provider-specific features (e.g. Ollama `think`) are passed through options and ignored by providers that don't support them.
- Model defaults are recorded in [model-eval.md](../model-eval.md) with the evidence behind them.
