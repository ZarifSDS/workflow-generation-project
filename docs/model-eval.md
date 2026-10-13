# Model evaluation

**Status:** method defined; results are filled in during milestone M2.

The goal is to choose default models for the `quality` and `fast` profiles using **your own briefs**, not leaderboards.

## Method

1. Pick 3 real briefs: one `seo_blog`, one `outbound`, one short `lead_magnet`.
2. Run the same step (outline, then draft) with each candidate through `scripts/eval_models.py` (M2). Prompts and settings stay identical; only the model changes.
3. The script records, for each candidate:
    - output text
    - time to first token, tokens/s and total time
    - peak RAM and VRAM (sampled from the host during local runs)
    - provider errors and retries
4. Score each output blind, 1–5, on the rubric below.
5. The deterministic quality checks (FKGL vs target, AI-tell scan, word count vs target) are recorded automatically.

## Rubric (score 1–5 each)

| Criterion | What good looks like |
|---|---|
| Accuracy | No invented regulations, figures or sources; claims flagged for verification |
| Structure | Follows the brief and outline; logical H2/H3 flow |
| Voice | Plain, expert B2B tone; no filler or AI tells |
| Search fit | Covers search intent; uses keywords naturally |
| Edit effort | How much work it needs before publishing (5 = minimal) |

## Candidates

| Tier | Model | Where |
|---|---|---|
| quality | Qwen3.8 27B | local Ollama |
| fast | glm-4.7-flash / a 35B-A3B MoE | local Ollama |
| quality (API) | 1–3 free-tier models you have keys for | see providers.md |
| optional | Larger MoE models you choose to pull | local Ollama |

## Results

| Model | Step | Score (avg of 5) | tok/s | Time | Peak RAM / VRAM | Notes |
|---|---|---|---|---|---|---|
| (filled in M2) | | | | | | |

## Decision

Defaults chosen (filled in M2):

- `quality`: …
- `fast`: …
- `image`: …
