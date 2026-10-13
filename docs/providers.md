# AI providers

**Status:** design for milestone M2. Nothing here is hard-coded. Each pipeline step references a **profile** (`quality`, `fast`, `image`), and each profile maps to a provider and model you configure.

## Text providers

All text providers are called through one **OpenAI-compatible** client (`openai` Python SDK), changing only `base_url`, the API key and the model.

| Provider | Base URL | Key env var | Notes |
|---|---|---|---|
| Ollama (local host) | `http://host.docker.internal:11434/v1` | none | Private, no limits; speed depends on host hardware |
| Ollama Cloud | `https://ollama.com/v1` | `OLLAMA_CLOUD_API_KEY` | Large open models; usage caps reset every 5 hours and weekly |
| Google Gemini (AI Studio) | `https://generativelanguage.googleapis.com/v1beta/openai/` | `GEMINI_API_KEY` | See the EEA/UK caveat below |
| Mistral | `https://api.mistral.ai/v1` | `MISTRAL_API_KEY` | Opt out of training in the console |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | `NVIDIA_API_KEY` | Generous request limits; usage is logged |
| Groq | `https://api.groq.com/openai/v1` | `GROQ_API_KEY` | Very fast, mid-size models |
| OpenRouter (free models) | `https://openrouter.ai/api/v1` | `OPENROUTER_API_KEY` | Free models may log prompts |

Free-tier limits change often; check each provider's current terms. Source list: [awesome-free-llm-apis](https://github.com/mnfst/awesome-free-llm-apis).

## Image providers

| Provider | How | Notes |
|---|---|---|
| ComfyUI (local host) | HTTP API at `http://host.docker.internal:8188` | FLUX.2 [klein] 4B (Apache-2.0, commercial use OK). Needs quantised weights on 8 GB VRAM. |
| Cloudflare Workers AI | REST, `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` | FLUX.2 klein 4B or FLUX.1 schnell; free daily allowance shared with text |

Avoid models with non-commercial licences (FLUX.1-dev, FLUX.2-dev, FLUX.2 klein 9B) for company content.

## Local model strategy (RTX 5060 Laptop 8 GB + 64 GB DDR5-5200)

Models larger than VRAM split across GPU and system RAM, and generation speed is then limited by memory bandwidth (about 83 GB/s here). Pipeline steps run in the background worker, so slower but higher-quality local generation is acceptable.

| Profile | Candidate (already installed) | Expected speed (estimate) |
|---|---|---|
| `quality` | Qwen3.8 27B (dense, ~17 GB). Prefer a stock build over an abliterated one for business copy. | ~4–7 tokens/s; ~10–20 min per 2,000-word draft |
| `fast` | glm-4.7-flash, 35B-A3B MoE models (~3B active) | ~20–35 tokens/s |
| larger MoE (optional) | MoE models up to ~110B total / ≤10B active at Q4 fit in RAM | Test in M2 before adopting |

The worker passes `num_ctx`, `keep_alive` and `think` per step. Before an image step it unloads the text model (`keep_alive: 0`) so ComfyUI gets the GPU.

**Choosing new models:** don't pull models based on leaderboards alone. Add candidates to the evaluation in [model-eval.md](model-eval.md) and compare them on real briefs. Useful searches: `best MoE LLM 64GB RAM Ollama writing quality`, `<model> Q4_K_M size active parameters`, `<model> long-form writing benchmark`.

## Data and compliance caveats

- **Free tiers may use your prompts for training.** Never send confidential, customer or unpublished commercial data to them. Public-facing drafts are lower risk, but still check each provider's terms.
- **Gemini free tier:** Google's terms restrict free-tier use for services offered to users in the EEA, Switzerland or the UK. Review the current terms before using it in production.
- **Mistral:** opt out of training on the free tier.
- **Local Ollama** keeps all data on your machine.
