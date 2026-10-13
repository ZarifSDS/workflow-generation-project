# Model evaluation

**Status:** M2 in progress. The outline round is running; results are added below after blind scoring.

Default models for the `quality`, `fast`, `edit` and `image` profiles are chosen by running **the same briefs and prompts through every free candidate** and scoring the outputs blind, not by leaderboards.

## How to run

All commands run inside the `web` container (`docker compose exec web …`).

| Step | Command |
|---|---|
| Check providers | `python manage.py ai_smoke` |
| Outline round | `python manage.py eval_models --round outline --run-dir eval/runs/r1-outline` |
| Draft round | Save the best outline per brief as `eval/outlines/<brief-id>.md`, then `python manage.py eval_models --round draft --models "<m1>,<m2>,…" --run-dir eval/runs/r2-draft` |
| Image round | `python manage.py eval_models --round image --run-dir eval/runs/r3-image` |
| Report | Fill in the run's `scorecard.md`, then `python manage.py eval_report eval/runs/<run>` |

- A run directory can be resumed: rerunning the same command skips outputs that already succeeded.
- Inputs live in `eval/`:
    - `briefs.yaml`: three realistic EHS briefs, each with an accuracy trap
    - `candidates.yaml`: the free models
    - `prompts/`: templates condensed from the blog skills
- Run outputs in `eval/runs/` stay local (git-ignored); only the summary tables below are committed.

## What each run records

- **Per output:** the text (labelled A, B, C… with labels shuffled per brief, so scoring is blind), time to first token, total time, tokens/s, and the GPU share of the model's memory (local Ollama).
- **Automatic hints** (`results.json` → `metrics`):
    - word count and FKGL against target, plus FKGL for each H2 section
    - primary keyword placement (H1, first 100 words, headings) and density
    - secondary keyword use
    - wrong US/UK spelling variants for the brief's region
    - accuracy-trap hits (good terms and red flags)
    - meta-narration count
    - `[VERIFY]` markers

  These are hints for the scorer, never verdicts.
- `key.json` maps labels to models. Open it only after scoring.

## Rubric (score 1–5 each)

| Criterion | What good looks like |
|---|---|
| Accuracy | No invented regulations, figures or sources; correct region and law; uncertain claims flagged |
| Structure | Follows the brief and outline; logical H2/H3 flow |
| Voice | Plain, expert B2B tone; no filler or AI tells |
| Search fit | Answers the search intent; keywords used naturally |
| Edit effort | How little work it needs before publishing (5 = minimal) |

## Briefs

| Id | Type | Region | Accuracy trap |
|---|---|---|---|
| `b1-sds-retention` | SEO blog (sdsmanager.com) | US | SDSs are exposure records (29 CFR 1910.1020); they may be discarded if a record of chemical identity, use location and dates is kept for 30 years |
| `b2-secondary-labelling` | Guest post | UK | COSHH and GB CLP, not OSHA; British spelling |
| `b3-lab-checklist` | Lead magnet checklist | AU | SDS review at least every 5 years; hazardous chemicals register; GHS 7 |

The traps are scoring hints based on the author's understanding of each rule. Confirm them before scoring Accuracy.

## Candidates (free, verified 2026-10-13)

| Provider | Models |
|---|---|
| Local Ollama | Qwen3.8 27B (abliterated build, `think` on), glm-4.7-flash, Ornith 1.5 35B-A3B |
| Ollama Cloud | nemotron-3-ultra, gpt-oss:120b, gemma4:31b |
| Gemini | gemini-3.8-flash, gemini-3.7-flash (Pro models have no free quota; the 2.5 generation is closed to new users) |
| Groq | qwen/qwen3.8-27b, openai/gpt-oss-120b |
| Cloudflare (images) | flux-2-klein-4b (1024×576), flux-1-schnell (8 steps) |

## Results

<!-- eval-results:start -->
<!-- eval-results:end -->

## Decision

Defaults chosen (filled in after scoring):

- `quality`: …
- `fast`: …
- `edit`: … (decided in M5's edit round)
- `image`: …
