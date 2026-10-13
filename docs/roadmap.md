# Roadmap

| # | Milestone | Deliverable | Status |
|---|---|---|---|
| M1 | Bootstrap and docs | Wagtail 8 project; Docker stack (web, worker, db, migrate); Postgres; healthchecks; Content Studio menu; tests; CI; docs | Done |
| M2 | AI layer and model evaluation | Provider registry; OpenAI-compatible and Ollama-native adapters; Cloudflare images; `ai_smoke`, `eval_models`, `eval_report` commands; results in model-eval.md; defaults chosen | In progress (layer built; evaluation running) |
| M3 | **Content Studio in Wagtail: UX and UI** | **3a UX design (reviewed by you before any build):** user flows, screen inventory, wireframes, states (empty/loading/long-running/error), copy, accessibility; see [ux.md](ux.md). **3b UI build:** data models (`ContentBrief`, `PipelineTemplate`, `GenerationRun`, `StepRun`); Studio dashboard, brief wizard, run workspace with step timeline and review panel; **provider/model dropdowns** (verified models only, free/paid marked); **title/meta/slug checklist with "Add your own"**; **brief presets** (screen + "Save current as preset"); **site crawl step** for guest posts; step versions (first draft + last three); admin-only notifications (sidebar badge, admin messages, review queue); built with Wagtail admin components so it looks and behaves like Wagtail | 3a done (2026-10-13; [wireframes](wireframes/content-studio.html)); 3b built (screens, data, actions; generation runs from M4) |
| M4 | Generation wired into the UI | Steps as background tasks run from the run workspace; approval gates; regenerate with a chosen model; retries and provider fallback; live progress and notifications | Built (2026-10-13); verified with a live run: research → hero image → done |
| M5 | Quality tools and review step | Wrap the skill scripts (deslop, clarity-review, clean-user-facing-text, metrics); the **review-and-edit sequence** in [workflow.md](workflow.md#review-and-edit-step-m5) (per-section grade scan → de-slop → clarity review → strip meta narration → word-level edits above grade 13 → re-scan → targeted splits); **edit-model evaluation round** | Built (2026-10-13); verified live on a real draft. Edit round ready to run once a draft is chosen |
| M6 | Images | ComfyUI and Cloudflare providers; VRAM handoff; vision check; sds-hero-stock branding ([hero step](workflow.md#hero-image-step-m6)) | Built (2026-10-13); verified live with Cloudflare + Gemini vision + branding. ComfyUI tested against a mocked API (not installed yet) |
| M7 | Publish and integrate | `ArticlePage`; moderation workflow; Markdown/HTML/DOCX export; optional n8n webhook ([publish step](workflow.md#publish-step-m7)) | Built (2026-10-13); verified live on run 9 (draft page in Moderators approval, all exports). Webhook tested against a mock |
| M8 | Hardening | Roles and permissions; secret handling review; database backups; production compose | Built (2026-10-13): four roles enforced server-side, login rate limiting, secret redaction and CI secret scan, nightly backups (restore tested), production compose with automatic HTTPS (validated, not yet run on a real domain), stuck-step recovery. See [security.md](security.md) |
| M9 | UI/UX overhaul | Rich-text editing of step output (Tiptap, Markdown dialect), richer article pages, admin theme ([plan](ui-ux-plan.md)) | Phases 1-3 built (2026-10-13); phases 4-6 next |

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
