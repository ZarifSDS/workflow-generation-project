# Plan: model prices and context windows, and a friendlier Content Studio (2026-10-15)

Plan only. Nothing is built until the owner approves; the owner picks the parts and the order.

## Part 1: price per input/output token and context window for every model

### What exists today

- `apps/ai/remote_models.py` reads each provider's model list. OpenRouter's list carries per-token prices and the context length, but they end up only as display text in `AddedModel.details` ("1050k context · $0.10 in / $0.50 out per M tokens"). Nothing can calculate with them.
- Built-in catalog models (`apps/ai/catalog.py`) have no price or context at all, only free/limited/paid.
- Every call already returns `input_tokens` and `output_tokens` (`GenerationResult`), but the studio throws them away: no step, run or chat message records what it used or cost.

### What each source can tell us (checked 2026-10-15)

| Source | Prices | Context / max output | Notes |
|---|---|---|---|
| OpenRouter `GET /models` | Yes: `pricing.prompt` / `pricing.completion` in USD per token, plus cache-read/write, per-request and per-image prices | `context_length`, `top_provider.max_completion_tokens` | Already read; only the numbers need keeping. OpenRouter also returns the **actual billed cost** in every response's `usage.cost` |
| Groq `GET /openai/v1/models` | No (prices are on its Supported Models web page only) | `context_window`, `max_completion_tokens` (the parser already reads `context_window`) | Free-tier key: list price is informational |
| Gemini (OpenAI-compatible list) | No | Not in that list; Gemini's native `models.list` gives input/output token limits | Free tier on the current key |
| Ollama Cloud | No (subscription) | No | Plan-based |
| Local Ollama | Free | `POST /api/show` gives the model's context length | Always $0 |
| Any added OpenAI-compatible provider | Sometimes (OpenRouter-style `pricing`, or per-million `input`/`output`) | Sometimes | Parse every common shape; unknown stays blank |
| **Reference list**: LiteLLM's `model_prices_and_context_window.json` (MIT licence, community-maintained, about 2.8 MB) | `input_cost_per_token`, `output_cost_per_token` | `max_input_tokens`, `max_output_tokens` | Covers Groq, Gemini and most hosts; matched by provider and model id. Labelled "reference price", never "your bill" |

### The mechanism

1. **A new table, `ModelInfo`** (provider, model): input and output price per million tokens, cached-input price (optional), context window, max output, a "free on this key" flag, **source** (provider list / reference list / OpenRouter listing / entered by hand), source detail, and checked date. It's additive: the existing `details` text, `status` and dropdowns keep working when a row is missing.
2. **One resolver, run by the existing model sync** (daily, on "Refresh model lists", and when a key is added). For each model it fills each field from the first source that has it:
   1. A value entered by hand. It is never overwritten.
   2. The provider's own list (OpenRouter prices; Groq, Gemini and Ollama context windows).
   3. The reference list, matched by provider prefix and a normalised id (`:free`, `models/` and date or version tags handled), with a match report so near-misses can be checked.
   4. Nothing: the field stays blank and shows "price unknown". The system never guesses.
3. **Billing per key, so the money shown is what is billed.** Settings › AI providers gets "How this key is billed": *pay per token* (OpenRouter, an added paid key), *free tier* (Gemini, Groq now), or *subscription* (Ollama Cloud). A free-tier or subscription key shows the list price for reference and "$0 billed".
4. **Adding a key is the whole setup.** When a key is stored, the sync lists its models and the resolver fills their prices and context at once, so nobody types prices. A "Prices" column in Manage models allows a manual fix that sticks, and shows each value's source.

### Where it shows

- **Model dropdowns**: "Luna latest · $0.10 / $0.50 per M · 1,050k context" (the filter box already handles long lists).
- **Choose models / Manage models**: columns for input price, output price, context window and source, sortable.
- **Default models**: each task shows its model's price and context.
- **Before a run** (the wizard, and the briefs list's Autopilot): an estimate such as "About 12 min · about $0.04 (2 paid models)". It uses typical tokens per step, measured from past runs once the ledger below has data, or a conservative default until then.
- **Context guard**: if a step's prompt plus its output limit would exceed the chosen model's context window, the model panel warns before the run, instead of the step failing midway.

### Recording what each run actually used and cost

- **A usage ledger, `UsageRecord`** (one row per model call): provider, model, task, run/step/chat or image job, input and output tokens, cost, and whether the cost was **billed** (OpenRouter's `usage.cost`) or **estimated** (tokens × price).
- It is written in `apps/ai/service.generate` inside a guard that never raises: a ledger failure can't fail a step. The run, step and chat context comes from a context variable that `execute_step`, the chat task and the image tasks set. No signatures change.
- **Run screen**: tokens and cost per step, and a run total. **Settings**: spend per provider and model, by day and month.
- SOP review rounds, the review-and-edit rewrites and tuning each count as calls, so the totals are the real cost of autopilot.

### Not breaking anything

- Additive migrations only. Every display falls back to today's text when a value is missing.
- Price lookups and the reference fetch run only during the sync, are cached in the database, and log errors to `ModelSync` the way failures are recorded today.
- Tests use mocked sources (respx) for each response shape, cover the resolver order (hand-entered wins), and check that a ledger failure leaves the step's output intact.

### Decisions for the owner

1. **Reference list**: fetch LiteLLM's file (a GitHub raw URL, read only during a sync) for providers that publish no prices? The alternative is OpenRouter's public listing as the reference, which covers fewer providers and shows OpenRouter's own price.
2. **Image models**: priced per image (OpenRouter, Cloudflare neurons) in this round, or text models only first?
3. **Spend limits**: later, a monthly cap per key that warns or holds autopilot when it is near. Want it?

### Built (2026-10-15): the owner approved the LiteLLM reference list, text models only

- **Code:** `apps/ai/pricing.py` (billing, reference list, resolver, `facts`, `cost`), `apps/ai/usage.py` (`scope`, `record`, `for_run`), `apps/studio/estimates.py` (tokens per step, context needed, `run_estimate`). Migration `ai.0005` adds `ModelInfo`, `PriceReference` and `UsageRecord`, plus `ProviderConfig.billing` (with a database default, so older code can still save rows). The setting `AI_PRICE_REFERENCE_URL` can be left empty to switch the reference list off.
- **Sources, in order:** a value typed on Manage models, then the provider's list (OpenRouter prices; the context windows of OpenRouter, Groq and local Ollama via `/api/show`), then the reference list. A pass that has no listing keeps whatever the provider gave. Local models cost $0.
- **Where it shows:**
  - every model dropdown (wizard, Default models, the run screen's model panels): "$0.10 / $0.50 per M · 1,050k context", "free tier (list …)", "on your plan", or "price unknown";
  - "context too small for this step" next to models that can't fit the step. The check uses the context a call actually gets (local Ollama's `num_ctx`);
  - the wizard's live estimate next to Start run;
  - the run's cost in the run-screen header, and each step's tokens and cost in its version line;
  - AI providers: "Billed as" per key, and "prices known";
  - Manage models: editable price and context columns, showing where each value came from;
  - a new **Usage and cost** page (Settings › AI providers): cost by month and model, and the latest runs.
- **Ledger:** every successful text call is recorded in `apps.ai.service.generate`. The worker tasks set the scope: step (including SOP rounds and edit passes), chat, image plan and image job. OpenRouter's `usage.cost` is stored as **billed**. Image generation isn't priced in this round.
- **Live check (2026-10-15):**
  - 3,135 reference entries were read, and the sync priced 462 models from the providers' lists and 27 from the reference list.
  - Luna latest shows $0.10 / $0.50 per M with a 1,050k context.
  - Groq gpt-oss 120B shows $0.15 / $0.60, the same as Groq's page.
  - Gemini 3.7 Flash shows $0.75 / $3.75 per M from the reference list.
  - Most Ollama Cloud models have no reference context.
  - The wizard renders in 1.2 s, as before.
  - Its estimate came to about $0.04 for the default Luna run, $0.06 with autopilot, and $0.39 with a $2.50 / $12.50 draft model.
- **Tests:** `tests/test_pricing.py` (19).

**Effort:** the table, resolver and display come to about 1.5 days. The ledger with run and settings totals is about 1 day. The pre-run estimate and context guard are about half a day.

## Part 2: Content Studio UI/UX (taste-skill audit, kept inside the Wagtail theme)

The audit used the taste-skill redesign checklist, filtered to what fits the Wagtail admin. **The owner's earlier decisions stay**: Palette B, Outfit for headings (`docs/ui-ux-plan.md`), Wagtail's components, dark mode, and no rebranding. The skill's font swaps, grain, glass and gradients don't apply here.

### Workflow: where a new user gets stuck, and the fix (highest value)

1. **On the run screen, the text comes last.** The version line, downloads, exports, the SOP self-review log and the review table all sit above the content (`run_workspace.html` ~l.60-159). The markers that block approval sit below the approve bar.
   - **Fix:** text first, then the markers, then the approve bar. Fold the SOP log, review sequence and grade detail into Wagtail tabs or disclosures: *Text · Checks · SOP log · Versions*.
2. **No "what to do next" banner.** Add one plain sentence per state, for example:
   - "The outline is ready. Read it, answer the 3 questions, then approve to start the draft."
   - "Autopilot is holding here: 2 [VERIFY] claims need you."
   - "Waiting for a worker, usually 2 min."

   The approve button says what follows: "Approve outline and start the draft".
3. **Six ways to revise.** Today there are: edit, send back and regenerate, send back as targeted edits, chat suggest or apply, the model panel's regenerate with a note, and Tune.
   - **Fix:** one "Change this" area with three choices: *Edit it yourself*, *Ask for specific changes*, *Write it again (choose a model)*. Tune stays in the grade table.
4. **The wizard asks for everything at once.** It shows about 15 fields plus a per-step table of model, SOP and gate, with lists of up to 515 models.
   - **Fix:** content type, then mode, then topic, keyword and region.
   - Fold "Reader and length (the defaults suit most articles)".
   - Fold "Advanced: models and approvals" behind a one-line summary: "9 steps · Luna latest · stops after research, outline, draft".
   - The guest-post sheet paste moves under Guest post.
5. **No time or cost preview before starting,** and the briefs list starts runs in one click. Add the estimate from Part 1. The list's Start and Autopilot buttons open the pre-filled wizard (or confirm first).
6. **Jargon.** "FKGL" becomes "Reading grade". "Slop index", "Mechanical sweep blockers", "SOP self-review", "deslop", "syll." and H2/H3 get plain labels with one-line descriptions. The developer note "runs once generation is connected (M4)" on the dashboard goes. The broken "What the SOP checks" link (`#sop` has no target) gets fixed.
7. **Auto-reload can wipe typing.** The run screen reloads when the run changes (`run_workspace.html:517`), losing half-written feedback or chat text. Skip the reload while a text box has unsaved text, and show "Updated: reload" instead.
8. **The step list is crowded.** Group it as *Plan · Write · Finish* with "Step 4 of 9", and keep model names on the step page. "Title and meta" goes into the flow before Publish, instead of a small header button.

### Visual and consistency fixes (small, within Wagtail)

- One primary button per view (Approve). Today up to six solid buttons can show at once.
- Callout severity through Wagtail's `help_block` (critical, warning, info) instead of one grey style for errors and notes.
- Numbers in Wagtail's sans with tabular figures (`.s-num`) instead of monospace; monospace only for ids and code.
- Help paragraphs capped at about 65 characters wide (some are 110 words across the full width), and output text at about 68ch.
- Fix the undefined `.s-stack--bottom` class and the `.s-list` clash (SOP bullet lists get card borders).
- The image generator's tabs use Wagtail's tabs or the existing segmented control, not buttons.
- `w-progress` on long submits (Start run, Refresh model lists, Make the image). Hover states on dashboard and metadata rows.
- Move the six inline scripts, including three copies of the polling code, into one `studio.js`. Key-value rows become `<dl>`; the grade bar becomes `<meter>`.

### Keep as they are

Wagtail headers and breadcrumbs, button classes, form fields, the messages framework, chooser modals, `--w-color-*` tokens (dark mode), disclosures rather than modals, `aria-current` in the timeline, and server-rendered timers.

### Order and effort

| # | Item | Effort |
|---|---|---|
| 1 | Run screen: text first, checks folded, markers above approve (W1) | M |
| 2 | Next-step banner and buttons that say what follows (W2) | M |
| 3 | One "Change this" area (W3) | M |
| 4 | Wizard folding and pipeline summary (W4) | M |
| 5 | Time and cost preview; no one-click runs (W5, needs Part 1) | M |
| 6 | Plain labels, broken link, dev note (W6) | S |
| 7 | No reload over unsaved typing (W7) | S |
| 8 | Visual fixes above | S-M |
| 9 | Grouped step list; Title and meta in the flow (W8) | M |

S is under half a day; M is half a day to a day. Each item ships with tests (HTML assertions, plus a check of the script-built UI in the browser pane) and keeps the existing suite green.
