# Roadmap

| # | Milestone | Deliverable | Status |
|---|---|---|---|
| M1 | Bootstrap and docs | Wagtail 8 project; Docker stack (web, worker, db, migrate); Postgres; healthchecks; Content Studio menu; tests; CI; docs | Done |
| M2 | AI layer and model evaluation | Provider registry and OpenAI-compatible client; Ollama tuning; `scripts/eval_models.py`; results in model-eval.md; defaults chosen | Next |
| M3 | Studio data and admin | `ContentBrief`, `PipelineTemplate`, `GenerationRun`, `StepRun`; Briefs/Runs/Prompts screens; run detail view | Planned |
| M4 | Pipeline and worker | Steps as background tasks; approval gates; retries and provider fallback; live status | Planned |
| M5 | Quality tools | Wrap the skill scripts (deslop, clean-user-facing-text, metrics) as checks and badges | Planned |
| M6 | Images | ComfyUI and Cloudflare providers; VRAM handoff; sds-hero-stock branding | Planned |
| M7 | Publish and integrate | `ArticlePage`; moderation workflow; Markdown/HTML/DOCX export; optional n8n webhook | Planned |
| M8 | Hardening | Roles and permissions; secret handling review; database backups; production compose | Planned |

## Verification for the full pipeline (end of M7)

1. Create a brief.
2. Start a run with the local Ollama provider.
3. The worker completes research; approve it.
4. Edit and approve the outline.
5. Draft, then edit; quality badges appear.
6. Generate a hero image (ComfyUI, with Cloudflare as fallback).
7. Create the Article draft; it enters the moderation workflow.
8. Export it as Markdown.
9. Stop Ollama mid-step: the step retries, falls back to the backup provider, then shows `failed` with a working retry button.
