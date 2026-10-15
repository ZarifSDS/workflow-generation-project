# Handoff: Content Workflow Studio (state on 2026-10-15, GMT+6: infographics built and wired in, model lists follow the keys, Luna is the default model, content-editing and reading-grade plan written)

Read this first in a new session. Then `docs/sop-audit.md` ("Where the audit stands" and each phase's section) before touching `apps/studio/sop.py`, `docs/infographic-audit.md` before touching `apps/quality/infographic.py` or the image planner, `docs/content-editing-plan.md` before changing checks or the reading grade, then `docs/development.md` (code map, how-tos, process), `docs/sop.md` (the SOP and the autopilot) and `docs/tools-and-processes.md`. Also see `docs/roadmap.md`, `docs/workflow.md`, `docs/ui-ux-plan.md`, `docs/security.md`, `docs/providers.md`, `docs/model-eval.md` and `AGENTS.md`.

## Fresh chat: start here (2026-10-15)

**State:** everything is committed and pushed (last code commit `0bb96f2`, CI green; since then only docs: the handoff, `docs/content-editing-plan.md` in `fb6d49f`, and this update); share mode runs it (migrations up to studio 0015 and ai 0004 applied). Suite: 578 passed, 1 skipped. Working tree clean.

**What exists now, in one breath:** the SOP-guided article pipeline (audit phases 0-8), the newcomer-reader default, the Image generator (photos: branded hero, unbranded lead image, in-article photo with the logo; and branded infographics from six templates, chosen per section by the article planner or made from a description, edited in a form with a live preview), model lists that follow the stored keys (515 listed models, Choose models / Manage models in bulk), and Luna latest (OpenRouter) as the default for every text task.

**Reading grade, done 2026-10-15:** the owner chose option C from `docs/reading-grade-options.md` (keep FKGL, fix the counting, add Hemingway/Yoast-style flags), and it is built: `apps/quality/readability.py` is the only counting everywhere, with hard and very hard sentences relative to the target (the tuner's input), the grade's two drivers, complex words and the passive share on the run screen. Suite 612 passed, 1 skipped. Read "Built" in that doc for the measured effect (graded sections on stored runs 170 → 56: no grade under 100 words) and the open items (skill parity, a larger gold set, dropping textstat from the image). Share mode runs it (rebuilt the same day).

**Model prices, context windows and the usage ledger, built 2026-10-15** (`docs/pricing-and-ux-plan.md` Part 1 › Built). Every model dropdown shows its price per million tokens and its context window. Values are resolved by the model sync: a hand-entered value first, then the provider's list, then LiteLLM's reference list. Each key has a "Billed as" setting, so free-tier and subscription keys cost $0. Every call is recorded with its tokens and cost. Costs show on the run screen and on a new Usage and cost page, and the wizard shows a live time and cost estimate with a context guard. Migration `ai.0005` is applied to the live database. Suite: 627 passed. **Next: Part 2 (UX), in the plan's order.**

**Next, in order:**
0. ~~**First: identify a more modern grade-level system**~~ (done, see above) (owner's request, 2026-10-15), the kind modern tools such as the Hemingway app use, before building anything from the reading-grade section of `docs/content-editing-plan.md`. Today every grade is Flesch-Kincaid (FKGL): the blog skill's heuristic in `apps/quality/vendor/ehs_seo_blog/scripts/metrics.py`, called through `apps/quality/scripts.py` `fkgl()` and `apps/quality/review.py` (`grade`, `grading_text`, `prose`, `vocabulary_floor`, `stacked_sentences`), plus `textstat.flesch_kincaid_grade` in `apps/ai/evaluation/metrics.py`. Establish from primary sources (the tools' own docs, not blog guesses) which formula each tool uses and what it flags beyond the grade: Hemingway (often said to use the Automated Readability Index; verify), Readable, Grammarly, Yoast, plus candidates such as ARI, Coleman-Liau, Dale-Chall (new), SMOG, Gunning fog and Lexile. Judge them for this content (EHS terms, acronyms, newcomer reader, the owner's rule that standard clearer words win even if the grade rises) and for being computable without a model. Then recommend whether to replace FKGL, report a second grade beside it, or keep FKGL with the counting fixes in the plan, and how the sentence-level flags (hard / very hard sentences, adverbs, passive voice) would map onto the existing scans and grade tuning. A recommendation for the owner first; build only after they choose.
1. **The rest of `docs/content-editing-plan.md`** (plan only, the owner picks phases): structure checks first (thesis, kept promises, no overlap, parallel step headings, word weight, how vs why; no line passes while a structural finding is open), then line scans and titles. Owner's decisions in it: question-form headings over benefit-led ones (benefit has no metric), and "keyword near the front" of titles is a soft ranking preference, never a filter.
2. **Demo-time live runs on the paid model** (Luna is already the default): one blog run and one guest-post run end to end; read each step's SOP panel and hold notes against `docs/sop.md`; run `manage.py sop_replay` and `tests/test_sop_fixtures.py` before and after any check change.
3. **Infographics with the team:** open a plan page and an infographic job page in a real browser once (the form editor's styling was only checked on unstyled snapshots); try the planner on two or three more published articles. Possible next templates from the audit (they need an icon set or bespoke drawing): paired rows, rising tiers, broad-to-specific panels; then the September-style ones (branching flowchart, pyramid, timeline, cycle). A "Make this visual" action on `[VISUAL:]` markers in Final cleanup would connect infographics to runs.
4. **Still open:** photo prompts' small deviations from the measured hero spec; a custom guest-post host's image size isn't measured by the crawl; the free planner model over-lists PPE (Luna should do better; check on the live run); sectional drafting; re-branding library images. Done since the last list: scan counts with what-to-do copy, measured durations in the model lists, one grade readout per step (UX audit item 4).

**Owner's standing decisions (2026-10-14/15):** write for complete newcomers, audience-agnostic angles, no persona, but headings keep the query-matching question form; guest posts are only generated, never pushed anywhere; a stored key is the opt-in for every model it lists (paid included); infographics follow the October "style A" and Inter; model setup must be intuitive, not manual.

## Sessions of 2026-10-14 and 2026-10-15 (newest first)

**2026-10-15: branded infographic templates.** `docs/infographic-audit.md` (audit, the live October style, the confirmed templates) and `apps/quality/infographic.py`: six templates (`steps`, `decision`, `columns`, `part_to_whole`, `bars`, `form_anatomy`) drawn in code in the hero-derived house style, with checks (fit, legibility at 800 px, WCAG contrast on what was drawn, counts, sources, figures from the article, house style, logo, alt text). Inter Regular and SemiBold added beside Inter Bold (official 4.1 release, OFL; downloaded with the owner's approval). `manage.py render_infographic <kind> spec.json out/` or `--example`; tests in `tests/test_infographic.py`. Then wired in (migration 0015): the article planner chooses photo, infographic template or nothing per section and fills each spec from the article (checked at plan time, figures against the article); the Image generator has an "Infographic" kind (template plus a description the model writes the spec from, or a pasted spec), with redraw from edited JSON. Live: the UK safe-system-of-work article gave four passing infographics in 32 s. Details in `docs/infographic-audit.md` › Built. The content is edited in a form built from `infographic.EDITOR_SCHEMA` (`static/studio/infographic_editor.js`), with a server-side Preview that shows the image and its checks before a job is made; "Edit as JSON" stays for power users.

**Latest session (after the audit), all committed and pushed; share mode runs it (migrations 0013 and 0014 applied):**
- **The default reader (owner's rule):** anyone new to the topic, whatever their job; audience-agnostic angles and headings; a standard, easy-to-read, enjoyable, informational tone; no persona (neither the author's nor a reader persona the prose plays to). Headings still follow real queries and the ranking pages, leaning to question-form H2s (owner's follow-up: this rule never changes a heading's form). Where it lives: `_rules.md` (first rule), `outline.md`, `draft.md` (writer role is now "an experienced writer who knows EHS", the skill's ROLE=writer), `types.yaml` (intro opener: a generic example anyone can picture or a pain point a newcomer recognises), `sop_rubrics.md` (angle/headings, voice, glossing flipped: domain terms are glossed for the default reader). New briefs default to **Beginner**; the audience field is optional ("Reader" row in the brief table). Migration 0013 cleared the seeded job-title audiences and the "B2B SaaS readers who are busy and practical" lead from the regional profiles (edited profiles kept). At beginner, the draft prompt carries the skill's `plain-explanation-exemplar.md` (vendored, in the manifest) as the style reference. A brief can still name an audience or set Practitioner/Expert.
- **Hero items from the audit closed** (details in `docs/sop-audit.md`, phase 8): guest posts get an unbranded lead image at the host's size and an **Export** step (no `ArticlePage`); the skill's WebP and layered SVG are kept and downloadable (`fonttools` added); the article template serves WebP; vision findings carry severity (`low` doesn't hold) and text boxes (text under the veil doesn't hold); the vision check writes alt text.
- **Image generator** (Content Studio › Image generator; `apps/studio/imagegen.py`, `views/images.py`, models `ImagePlan`/`ImageJob`, migration 0014, tasks `run_image_plan`/`run_image_job`, `tests/test_imagegen.py`). Two ways in: **For an existing article** (pick a studio run, a published sdsmanager.com article from the internal index, any sdsmanager.com URL, or paste the text; the model reads it with `prompts/image_plan.md` and proposes the hero with the real H1 plus up to four in-article photos, writer's `[VISUAL:]` photo cues first; chart/diagram cues are listed as "not photos"; edit, tick, make) and **From a description or photo** (blog hero, unbranded lead image at any size, in-article image with the logo in a chosen corner; a description, your own prompt, or an uploaded licensed photo). Every image gets the vision check; a job page offers PNG/WebP/SVG downloads and "same photo, these settings" (new headline, size or corner). Only sdsmanager.com pages are fetched (robots respected). Not yet run live with real models.
- **Defaults set to OpenRouter's Luna latest** (owner's request, 2026-10-14): `openrouter::~openai/gpt-luna-latest` is the default model for all 11 text tasks (site crawl, research, outline, draft, review and edit, localise, hero photo prompt, suggestions chat, section tuning, SOP reviewer, hero image check); hero image generation keeps its own model and every fallback stays built-in. Checked live first: text in 2.6 s, image reading correct. $0.10 in / $0.50 out per M tokens, 1,050k context; every step now bills the OpenRouter key.
- **Choose models** (was Add a model) is a checklist per provider: models in the lists are ticked, tick to add, untick to remove (listed ones hidden, hand-added ones deleted), hand-typed ids still possible; removals only touch the checkboxes the page showed.
- **Fixed: Default models dropdowns showed only Built-in and the saved choice.** Wagtail renders `extra_js` before the page content, so the inline script that fills the dropdowns from the shared `<template>` ran before the selects existed. Every inline script that touches the page now waits for `DOMContentLoaded` (Default models, Choose models, Manage models and the run screen, whose live step timers had the same bug); `select_filter.js` enhances after those handlers. `tests/test_workspace_panels.py` guards it. Verified in a browser on the rendered page: 24 dropdowns, 531 options each, Luna preselected, filter boxes work. Lesson: tests that read HTML don't run scripts; check script-built UI in the browser pane (render the page with the test client and dev settings, open the file from the session folder).
- **Every model a key gives access to is listed automatically** (owner's decision, amends ADR 0008: a stored key is the opt-in, paid models included): first live sync put 515 models in the lists (OpenRouter 456, Gemini 39, Ollama Cloud 13, local Ollama 5, Groq 2; built-in duplicates and non-chat models left out). Manage models edits, removes (hides) and restores in bulk; Add models takes several at once; long dropdowns get a filter box. Run screen (UX audit item 4): model lists show the measured median time per model for that step, one grade readout per step, and what to do about each quality-scan count. See `docs/development.md` › Provider keys.
- **Add a model lists the provider's models** (owner's request after adding an OpenRouter key): Settings › AI providers › Add a model reads the provider's own list (`apps/ai/remote_models.py`; live: OpenRouter 462 models with 17 free, Groq 11, Gemini 63, Ollama Cloud 18, local Ollama 12) into a grouped, filterable dropdown; name and free/paid fill in. See `docs/development.md` › Provider keys.
- **Image generator, first live runs** (hierarchy-of-controls article): the plan step works (7-11 s); the hero branded cleanly; an in-article photo of labelled drums got garbled text and an invented logo, which the vision check held. Fixed at the source (`f4bdaa7`): no text-dependent scenes in plans, container contents never named in photo prompts, a no-text clause appended to every photo prompt. The free planner model still lists PPE items despite the prompt; Gemini (vision) returned server errors that cost minutes of retries.
- Guest posts: the owner said (2026-10-14) they're only for generating the post per the SOP, not for pushing anywhere; the guest-post stress tests were only updated to the Export step, not extended.

**State before that:** all eight SOP audit phases are committed and pushed (last audit commit `c86d9e0`, CI green). Suite: 502 passed, 1 skipped (the vendor drift test skips in containers, where `~/.claude/skills` is absent). Replay of runs 18-21 (latest versions): 44 → 22 blocking findings, all real defects. Fixture A (the owner's five approved articles) raises zero blocks; Fixture B catches all its planted defects. Share mode runs the latest image.

**What the SOP is for (owner's framing):** an agent in the backend that guides the content workflow: it classifies each finding by level (strategic → hold, structural in an article → send the draft back once, line → revise, mechanical → script), not just a list of checks. The owner's `content-editing` skill (Ryan Law's *How to Edit*; `D:\ai-memory-vault\skills - zipped\sds-manager\SKILL.md`) is the model for those levels; the mapping is in `docs/sop-audit.md`.

**For the owner, not code:** the published AU WHS risk-management article links a slug that 404s. Planned slugs are in public history from `ee24d43`; a history rewrite is the owner's call.

**Outside the repo (2026-10-14):** a corrupted passage in the `ehs-outbound-blog` skill (`references/voice-and-style.md`, Backlink section: a cut-off partial-match sentence with a "Link targets" paragraph and a stray registry row spliced in) was repaired in both `~/.claude/skills/ehs-outbound-blog/` and its `synced/` copy. No intact original existed, so the partial-match sentence was completed to match the studio rubric (`sop_rubrics.md` `draft:outbound`, "a partial match where the exact text won't sit grammatically"), which needed no change. The stray row is the Audit & Inspection entry already in `data/product-link-registry.json`. If the skill is re-uploaded to claude.ai, upload the repaired file.

**Working rules:** commits as ZarifSDS <zarif@sdsmanager.com>, ask before each commit and push; the repo is public (no internal plans, unreleased slugs or the share URL); never touch `D:\backups`; guest-post fixtures stay in the git-ignored `tests/fixtures/sop/a_local/`; no Python with backslashes through Bash heredocs; rebuild with `build web` then `up -d --no-deps --no-build --scale web=2 --scale worker=2 web worker` (never a plain `up` with the tunnel); any model `help_text` change needs a migration (CI runs `makemigrations --check`); CI is read through the GitHub REST API with curl (no `gh`).

## Session of 2026-10-14 (10:20 GMT+6 on): backend smoothing, then the SOP audit

**User direction this session:** the remaining text problems (wrong citations, flat tone, lenient reviews) are model reasoning; don't keep trying free models. Smooth the backend instead; a paid model is checked at demo time. Then audit the SOP against the five skills (`ehs-seo-blog-optimized`, `ehs-outbound-blog`, `deslop`, `clarity-review`, `sds-hero-stock`, with their references and data) to reduce or eliminate misfires by design rather than by endless stress tests.

**Runs this session (brief 16, gpt-oss:120b writer):** run 20 with nemotron-3-ultra as SOP reviewer (held at review_edit after four draft regenerations on successive fixes), run 21 with gemma4:31b (held at research: the reviewer read "URLs only from the inputs" as "every source needs a URL"; rubric clarified). nemotron: concrete first-round findings, then PASS with zero findings while blocks and stuffed headings remained; gemma4: loops on rubric ambiguity. The SOP reviewer default is back to the built-in (gpt-oss:120b); no TaskDefault row.

**Fixed (all with tests; suite 452 passed, ruff clean; share mode rebuilt on it):**
- Reviser told the length floor (`sop.length_rule`) and, on article steps, the only pages it may link (`sop.link_sources`); it reinvented URLs every round without the list.
- Draft revisions may reword a heading in place (count and order kept); the keyword checks asked for exactly that and every such revision was refused.
- Keyword in headings matched loosely (`sop.carries_keyword`: acronyms like SDS, plurals, any order); stuffing (keyword in > 3 headings) blocks; first body H2 must answer the query (advisory, `first_h2_answers`). Exact match had made the model append the keyword to every H2.
- Links in pointer sentences and flagged regulation references are droppable by a revision (the guard deadlocked on them); `LINK_CARRIER` now reads past the dots inside URLs.
- New blocks: a link to a bare path or a marker (`RELATIVE_LINK`); a regulation subsection (`1910.1200(c)(1)`) not in the research or search results unless its sentence carries `[VERIFY]` (`check_citations`); a blog close with no product-page link, or linking an article; a heading that joins topic and qualifier with a comma (house style: colon; `_rules.md` and the rubric now say so too).
- Mechanical fixes: `[text][url]` and `[text]([VERIFY])` repaired; markers with spaces or lower case normalised, and **the publish guard now reads them** (`[ SRC: url ]` used to pass Final cleanup and Publish); `Tags:`/`Excerpt:` lines under the H1 taken out of the article (`textclean.strip_metadata_lines`, in the draft split and in the loop).
- The skill's `link_check.py` and `editorial_flow_check.py` vendored and run on every article round (`sop.check_skill_scripts`): banned link placements block, flow prompts advise (at most six).
- **Guest-post intake from the sheet:** "Guest post from the brief sheet: paste a row" on the wizard (`apps/studio/sheetrow.py`), tested on every row of the real sheet: header-or-not, multi-line anchors, URLs split by spaces or lines, missing `https://`, ranges, placeholders, host linking rules in the anchor cell (moved to notes), region from URLs/notes.
- **Questions for the Requester as a form** on a research step waiting for review (`apps/studio/requester.py`): answers are written into the research as "Answer from the requester:" lines and saved as an edited version, so the outline and draft read them. Parser handles every shape gpt-oss wrote in runs 17-21; the research prompt now pins `1. Question? Assumed answer: …`.
- Metadata screen: own options get house mechanics (dash to colon), slugs normalised, over-limit own options refused, saving a selection with an over-limit option refused with a message, adding your own meta/slug/tags/excerpt now replaces the previous choice (two were selected before), and the search preview shows the real path (`sdsmanager.com › us › sds-management-articles › slug`, or the host for a guest post).
- The model panel on a step that hasn't run yet says "Run with … / Use this model when it runs".

**Still open from the audit list:** item 4 (one grade/checks panel per step, scan counts with what-to-do copy, send-back model list with durations) and sectional drafting / re-branding library images.

**The SOP audit is in `docs/sop-audit.md`** (read it before touching sop.py): six root causes, the phased plan and the owner's open decisions. Phase 0 is done (not-live index rows removed, every `[VERIFY…]` form held, `[VERIFY]` kept inside its sentence). Phase 1 is done: `manage.py sop_replay` (offline replay of the checks over stored runs) and `tests/test_sop_fixtures.py` (Fixture B with 16 planted defects, all caught; Fixture A waits for the owner's approved articles); the baseline is recorded in the audit doc. Phase 2 is done (see the audit doc's phase 2 section): findings carry a level and permissions, revisions are re-checked, structural findings send a draft back once, the reverse outline runs, edit rewrites are accepted per section, and Fixture A holds the owner's five approved articles (two published blogs committed, three guest posts in the git-ignored `tests/fixtures/sop/a_local/`), all at zero blocks. Phase 3 is done (audit doc, phase 3 section): `types.yaml` holds each type's check profile and prompt structure; guest posts and localise follow their own rules. Phase 4 is done (heading variants, FAQ fence, comma-to-colon, URL canonicalisation, the underline placeholder; FAQ answers may now carry links, by the owner's rule). Phase 5 is done (two lists to the reviewer, measurements, data-backed inputs, reviewer tags [strategic]/[structural] that route, concrete values for the reviser, hold notes with themes). Phase 6 is done (false positives in the pointer, coverage, meta-narration, density and link_check checks; see the audit doc's table). Phase 7 is done (the edit step: grading prose only, a per-section vocabulary floor, stacked sentences named for the tuner, the repeated-subject refusal, deslop/clarity inputs). Phase 8 is done (hero: 16:9 crop, Unchecked holds, placeholders, H1 headline, re-vendored scripts; the vendor manifest and drift test). **All eight phases are done**; see "Where the audit stands" and the open hero items in the audit doc. Next: a live blog run and a live guest-post run on a paid model at demo time, read against the SOP panel and the hold notes; then the open items (guest-post hero/publish as an export, WebP/SVG outputs, vision severity). Run the replay and the fixtures before and after every check change.

## Session of 2026-10-14 (03:45–07:50 GMT+6): what changed and where it stands

The user's brief for this session: audit the studio against how they actually brief work in Claude Code (their two prompts for `/ehs-seo-blog-optimized` and `/ehs-outbound-blog`, plus `/deslop`, `/clarity-review`, `/sds-hero-stock`), stress-test everything without publishing to sdsmanager.com, and build the one-shot "SOP agent": a self-reviewing mode that keeps the per-step review mechanism but lets the model review its own output against the SOP at each step and loop until the content meets it. Stop conditions were the clock (07:50 GMT+6), context, credits, or "the best I can produce"; then update this handoff, commit and push (the backup under `D:\backups` untouched).

### Built: the SOP self-review and autopilot

- **The SOP** is written down in `docs/sop.md` (inputs, deliverables per step, deterministic checks, reviewer rubric, the loop, where autopilot stops, how to run and tune it). It distils the skills and the user's prompts; where it and a skill disagree, the skill wins.
- **Code:** `apps/studio/sop.py` (checks per step, `run_loop`, `apply`), prompts `sop_review.md` (reviewer: `VERDICT: PASS|REVISE` + numbered Findings and non-blocking Suggestions, never rewrites), `sop_revise.md` (the step's own model applies the findings and changes nothing else), `sop_rubrics.md` (one `## step` section each). `tasks.execute_step` calls `sop.apply` after the executor when `step.self_review` is on; a reviewer failure never fails the step (output kept, step holds). Before each round the loop auto-fixes house mechanics, normalises the fixed headings (`Key Takeaways`, `Frequently Asked Questions`) and repairs `**[text]**(url)` links. A revision is used only if it keeps every `##` section by name and most of the words, plus (draft) every link and negation, or (edit, localise) every protected span and negation except URLs the checks flagged as invented. At most six reviewer findings go into a revision; two refused revisions in a row end the loop. **Deterministic checks worth knowing:** section shape per step, keyword placement, Key Takeaways and FAQ shape, generic close, anchors never adjacent, brief anchors exactly once, meta narration, density, and **every sdsmanager.com or wagtail link must appear in the inputs** (index, product registry, brief anchors, search results, research, outline), else it blocks as an invented URL.
- **Data:** migration `0011`: `StepRun.self_review`, `GenerationRun.autopilot`, `ContentBrief.anchors` (guest-post `anchor | URL` pairs) and `ContentBrief.source_reference` (sheet row). New model task **SOP reviewer** under Settings › Default models (`edit` profile by default). Setting `STUDIO_SOP_MAX_ROUNDS` (default 2).
- **UI:** wizard mode switch **Review each step / Autopilot (one-shot)** with a per-step **SOP self-review** column (JS clears the approval boxes in autopilot; the server reads the boxes, so any step can still be gated); **Autopilot** button on the briefs list; the run screen shows an Autopilot tag, "SOP passed/held (n rounds)" in the timeline and an **SOP self-review** panel with every round's verdict, check findings, reviewer findings and whether the revision was used; the runs list shows a Review button on steps waiting.
- **Rubrics vendored from the reference files** (the user's follow-up after reading run 18's output: headings formatted badly, flat tone, no interconnection): `sop_rubrics.md` now carries voice, reader-flow, formatting, ai-patterns, linking, step-2 and localization rules per step, plus `draft:outbound` / `review_edit:outbound` sections from the outbound skill (`docs/sop.md` §6). Dashes in headings and titles become colons. The reader-flow rule is also in the draft prompt. Not yet re-run live: the next session should run one autopilot brief on this rubric set and compare the SOP panels with run 18's.
- **Prompts aligned with the user's briefing prompts:** `_rules.md` now carries regulation-light-by-default (cite the parts of a rule the supporting queries and the ranking pages call for, never a tour), standard clear words over simpler ones even when the grade rises, no metaphors, and the intro's "this article" / "walk you through" scope sentence. Research gained **Regulation Depth**, **Anchor Opportunities** and **Questions for the Requester** (with assumed answers, so autopilot can proceed); Outline gained a **Keyword and Anchor Map**, depth-per-section from Regulation Depth and Cannibalization, and the anchor-adjacency rule; the Draft intro is now example-or-pain-point → why it matters → snippet → scope sentence. `types.yaml` now sets per content type the publication, the conclusion rule (blog: verb-first CTA heading, gap → action → one **product page**, never an article or lead magnet; guest post: host's closing style, no product link) and the linking rule (guest posts: each brief anchor exactly once, never adjacent, first in the first 30%, none in the close). Guest posts carry a region like blogs.
- **Tests:** `tests/test_sop.py` (19: checks, loop, hold, bad revision, reviewer failure, wizard, briefs list, anchors, type-specific prompts). Full suite 322 passed before the stress file was added; see "Stress test" below for the final count.

### Fresh chat: the remaining fine-tuning (where to pick up)

State at hand-over (2026-10-14 ~08:45 GMT+6): everything pushed; share mode on the latest image; **runs 18 and 19** are the comparison record (same brief 16, gpt-oss:120b as writer and reviewer; 19 on the vendored rubrics). Read `docs/sop.md`, then the SOP panels of runs 18 and 19 step by step. What the user still sees wrong in run 19's text, and what is in place against it:

1. **Pointer sentences instead of natural anchors** ("For a deeper look at X, refer to the X guide", "To manage changes, see the management-of-change resource"): now a blocking check (`sop.LINK_CARRIER`), a rubric rule (every anchor self-justifying: the sentence states a fact or fix and would exist without the link; pointer sentences are removed, never reworded) and the same text in `types.yaml`'s seo_blog linking rule. Not yet seen live.
2. **EHS solution anchors**: the user wants the product (EHS Solution by SDS Manager module pages) anchored in the sentence that resolves the pain point just described, plain and non-promotional, and never a sentence written for the link. Rubric says so; the forced-mention test is in the draft rubric. The deterministic side can't judge naturalness; a model with better register is the lever.
3. **Meta narration** still seeps in ("This section outlines…" is now caught; watch for new forms and add them to `META_NARRATION`).
4. **Keyword forcing**: the rubrics say never force (outline, draft, edit) and the advisory check says so, but gpt-oss oscillates between "keyword missing" and "keyword stuffing". The intro still opens on the keyword sentence instead of the pain point.
5. **Tone and flow**: run 19 improved every measure (FKGL 10.8 → 9.2 at edit, slop 9 → 4, sections over target 10 → 6, invented URLs 6 → 0) but reads mechanically; grade tuning by gpt-oss unpacks by repeating the subject. Next experiment: the same brief with a different reviewer (nemotron-3-ultra, gemma4:31b) and separately a different writer (local Qwen 27B), compared on the SOP panels.
6. **Length drift**: revisions trim (two refused per step for "too much text was removed"); run 19 ended 250 words under the guide. Consider telling the reviser the word floor explicitly.
7. The guest-post path (`draft:outbound` rubric, advisory shape checks, anchors on the brief) has not been run live at all.

Working rules that saved time this session: never put Python with backslashes through a Bash heredoc (write the script with the Write tool and run `python -I`); rebuild with `build web` then `up -d --no-deps --no-build --scale web=2 --scale worker=2 web worker`; drive a run from a one-off container with the scratchpad scripts (`start_rerun.py`, `approve_step.py`, `regen_step.py`, `resolve_cleanup.py`, `run_status.py`, `compare_run.py`; recreate them from `docs/sop.md` if the scratchpad is gone).

### Audit findings applied and still open

Applied this session (from the UX/process audit in this session's scratchpad, not in the repo): the Publish step's dead-end "Send back with feedback" (a required textarea with no submit button) is hidden where no model or chat applies; article checks no longer show on research and outline; the CTA field is hidden for guest posts; the wizard's search-step note points at Settings › Search data providers; editing an existing brief makes **Save brief** the primary action (starting a second run was one click away); the runs list has a Review button; the user guide's meta limit matches the model (160).

Still open, in priority order (details and file:line were in the audit; re-derive from the code):
1. Guest-post intake from the Google Sheet row itself (a "paste the row" or Drive-read intake that fills site, title, keyword, supporting keywords, anchors, word count, notes). The fields now exist on the brief; the import doesn't.
2. The barebones (headings-only) outline as its own artefact/export (it is a section of the outline version today).
3. Surfacing "Questions for the Requester" as a form on the research step whose answers feed the next steps (today they are plain Markdown with assumed answers).
4. One grade/checks panel per step instead of three readouts; quality-scan counts with "what to do" copy; Regenerate panel hidden on skipped or waiting steps; send-back model list with durations.
5. Metadata screen: refuse over-limit options and dashes; the sdsmanager.com preview URL is hard-coded.
6. `link_check.py` and `editorial_flow_check.py` from the skill as deterministic SOP checks; sectional drafting; re-branding library images.

### Stress test

- **Automated:** `tests/test_stress.py` (66 tests, written by a sub-agent against the pipeline and state machine with fake providers: full runs for all four content types with gates on and off, markers through cleanup and publish, hostile model outputs, state-machine edges, protected spans, metadata, permissions, the outbound crawl over respx). It found eight real bugs, all fixed in this session; the tests that documented them now assert the fixes:
  1. Publishing dropped the article's opening paragraph whenever an excerpt was selected (`publishing.save_draft` + `markup.build_article`): the intro now stays in the body unless nothing else fills the page Intro, and a heading-less article never publishes with an empty body.
  2. An empty or whitespace model answer became a reviewable version; it now fails the step with a retry message (`executors.model_text`, which also normalises CRLF and unwraps a Markdown code fence around the answer).
  3. `request_regenerate` had no status guard (a running step could be generated twice; an approved step could be re-queued): refused now, and the Model panel is hidden on running, approved and skipped steps.
  4. `approve_step` accepted an empty edit; refused now.
  5. `review.protected_ok` let an unrelated "not X but Y" license dropping a different negation; only an unfoldable negation that actually disappeared counts now.
  6. `add_own_metadata` crashed (HTTP 500) over 500 characters; refused with a message.
  7. Model output with CRLF was stored as is; normalised.
  8. A draft wrapped in a code fence kept the opening fence in the article; unwrapped.
  Full suite at the end of the session: **410 passed** (`python -m pytest -q --ds=config.settings.test -p no:cacheprovider` in a one-off dev container, ~100 s); ruff clean.
- **Live (real models, nothing published outside the local Wagtail):** autopilot **run 17** ("[Autopilot test] How to read a safety data sheet", seo_blog, US, gpt-oss:120b on Ollama Cloud for every text step and as the SOP reviewer, DuckDuckGo search results). Search results 37 s; research 47 s including a full SOP loop (review, revise, review, revise, review) and then **held** as designed. What the first live loop taught, and what changed because of it: the model's plans carried em-dashes, curly quotes and horizontal rules that it couldn't reliably fix itself (now `house.mechanical_fix` runs before every check round and is logged as "auto-fixed"); the questions check counted only list items while the model used a table (counts tables now); "No direct overlap" didn't match the cannibalization check (looser now); the reviewer flagged valid URLs because it couldn't see the search results (plans' reviewers now get the search results and the internal index); a rejected revision ended the loop (the next round now reviews the unchanged text and tells the model why its revision was refused); and the reviewer invented rules beyond the rubric (it now has a non-blocking **Suggestions** section, must quote the rubric rule it applies, and a REVISE without findings counts as PASS). **Run 18** re-ran the same brief on the fixed code, with the outline regenerated after each further fix:
  - Research: findings 10 → 8 → 2 over three rounds, mechanics auto-fixed, and the reviewer caught a fabricated statistic ("reduces reading time by up to 30%, internal testing"), then held. I removed that claim and approved, as an editor would.
  - Outline, first attempt: held because the model wrote `H2: Intro` as the second headings-only line (now ignored) and the reviewer talked it into rewording `Key Takeaways` into a query (fixed components are now normalised mechanically and the reviewer is told never to touch them). Second attempt: every revision dropped a `##` section (research plan sections, the headings-only block), so revisions are now refused when a section disappears by name, at most six reviewer findings go into a revision, and two refused revisions in a row end the loop. Third attempt: all deterministic checks clean from round 2 on; the reviewer still returned REVISE with judgment findings, some self-contradictory ("exceeds the 1,400-word target" and "not calibrated to the 2,400-word median") or invented ("no more than nine H2s"), and the model's revisions were refused for dropping sections. Held for a person; I approved it to run the rest of the pipeline. **Conclusion:** the loop, the checks, the guards and the hold all work; on plans, gpt-oss:120b as reviewer is the ceiling (it invents rules and its revisions restructure). Try a different reviewer model under Settings › Default models › SOP reviewer (nemotron-3-ultra or gemma4:31b on Ollama Cloud are free; a local Qwen is slower) and compare the logs; the per-step rubrics may also be tightened to say what is *not* a rule.
  - Draft (94 s with a four-round loop): the reviewer demanded a metadata block (the executor had split the options off; the rubric now says so), revisions were refused by the protected-span rule for wording changes (drafts now use the lighter guard), and the model wrote `**[text]**(url)` links that aren't links (repaired mechanically now). On the fixed code the loop added internal links round by round (0 → 1 → 2) and held with legitimate findings (unsourced speed claim, first H2 not answer-first) plus three **invented URLs** (`https://sdsmanager.com/library`, `wagtail://sds-management-overview`) that nothing caught: the URL-sourcing check exists because of this. Approved to continue.
  - Review and edit (133 s including the skill's edit sequence and the loop): the URL check caught six invented links; the first attempt couldn't remove them because URLs are protected spans (fixed: flagged URLs may be dropped); the second removed them all and fixed the keyword placement (check findings 8 → 4 → 1), then held because the reviewer counted the removed links as dropped spans (rubric clarified). Approved to continue.
  - Final cleanup: held on `[VERIFY]`, `[SRC:]` and `[VISUAL:]` markers as designed (56 narrow no-break spaces removed). Resolved as an editor would and approved.
  - Hero image (63 s, Cloudflare FLUX + Gemini 3.7 Flash vision + branding): branded, with flags for garbled text on a laptop screen and documents; in autopilot it continued anyway, so the hero step now **holds when the vision check reports readable text or a safety problem** (a person must look at those). Publish (0 s): created draft page 7, `how-to-read-safety-data-sheet`, not live, in the Moderators approval workflow, hero attached, intro and blocks in place. **Run 18 finished `done`** with three human touches (research, outline, draft/review approvals plus the marker resolution), each at a hold the SOP raised for a real reason. The selected title carried an en dash and non-breaking hyphens, so metadata options now pass through the house mechanics too.
  - **What a new session should do first with autopilot:** run the same brief once more from scratch on the current code (every fix above landed after the step it came from had already run), read each step's SOP panel, and tune the rubrics and the reviewer model from what it shows. The repo's tests cover every check and guard; the live behaviour of a given model is the remaining variable.

### Things a new session must know (added this session)

- **Share mode is running on the new image** (web ×2, worker ×2 rebuilt and restarted on 2026-10-14 ~04:10 GMT+6; ngrok and Caddy untouched). The database has migration 0011 applied. The automated-permission classifier here refuses `docker compose … up` with the share file because it includes the ngrok tunnel; rebuild with `build web` and restart with `up -d --no-deps --no-build --scale web=2 --scale worker=2 web worker` instead, and apply migrations with a one-off dev container.
- `apps/studio/prompts/types.yaml` keys `publication`, `conclusion` and `links` are mandatory for a content type (prompting fills `{{publication}}`, `{{type_conclusion}}`, `{{type_links}}`).
- The SOP's deterministic checks are strict about shape (`H2: Key Takeaways` second, FAQ last with 3-7 `H3:`, verb-first close): a model that formats plans differently will loop and hold. Loosen in `sop.py` with a test, never by editing the rubric alone.

## Where we are (state before this session, kept for context)

**Everything is committed and pushed** (see `git log`; the last commits are fa78bbe "Company CMS page types and default models per task" and the "Skill-aligned pipeline" commit after it). Tests: 303 passed; frontend 40 passed; ruff clean. Share mode is running, rebuilt with the latest code (`--build`, 2 web + 2 worker). No step is queued or running.

The user's direction:
- A fast, functional, visually better version of the current Wagtail CMS with better UX. No rebranding.
- The page types replicate the company CMS (https://cms.sdsmanager.com/admin/, Wagtail 6.3, headless) 1:1, improved where we judge it better. Inspect it through Claude in Chrome in the user's Brave (logged in; read only, never save there) instead of asking for screenshots. JavaScript that returns hrefs/query strings is blocked there; use get_page_text and find.
- The pipeline follows the user's `ehs-seo-blog-optimized` skill (`~/.claude/skills/ehs-seo-blog-optimized/`) for research, outline and draft. Its Step 3 is NOT used: Review and edit = scan, then a /deslop rewrite, then a /clarity-review rewrite, then grade tuning.
- Final goal: once tuned, one-shot generation of the whole pipeline. For now, smooth the step-by-step workflow.
- The user asks before each commit and push.

### The pipeline now (what each step does)

| Step | What happens | Code |
|---|---|---|
| Search results (first, optional, automatic) | Top 10 results for the brief's locale from the first configured provider (Serper, Brave, Google Programmable Search, then keyless **DuckDuckGo** as the default, then Ollama web search with the Ollama Cloud key); Google autocomplete (keyless); reads the top pages politely and measures H1–H3 outline, title tag, date, words, FKGL, FAQ, tables, video, forms, question H2s | `apps/studio/serp.py`, keys under **Settings › Search data providers** |
| Research | Skill Step 1: Search Intent, What Ranks, **Must Include**, **Missing Opportunity** (no "Do better", by the user's choice), Keyword Table, Questions, Sources by tier, Claims with status, Misconceptions, **Cannibalization** against the vendored internal article index | `prompts/research.md`, `apps/studio/houseref.py` |
| Outline | H1 options, format + length vs the ranking median, H2s as real queries, H3 necessity test, ~30% rule, per-section words, capsules, Intro/Conclusion/FAQ plans (product from the vendored registry), claim table, structure decisions with alternatives, headings-only outline (Key Takeaways first, FAQ last). Article headings are written as `H2:` lines so the plan isn't graded as an article | `prompts/outline.md` |
| Draft | Skill Step 2 + component specs: sees the research; intro with the literal "this article" scope sentence, Key Takeaways, core in the first H2, capsules, `[SRC: url]`, `[VISUAL: …]`, verb-first CTA conclusion with one registry product (+ button label when CTA style is button), FAQ (`:::faq`), References; house style (no dashes, straight quotes, Title Case); metadata with 3 options each for Meta Title, Meta Description, Slug, **Tags**, **Excerpt** | `prompts/draft.md`, `prompts/_rules.md`, `textclean.split_metadata` |
| Review and edit | Scan (deslop lexical with the skill's banned-word TSV and Title Case allowed, structure, redundancy; clarity frame scan with the keywords as terms; whole-article metrics) → **deslop rewrite** → **clarity-review rewrite** → **grade tuning** per H2 (H3s in sections over 300 words), more than 1 above target, hardest first, max 10, by syntactic unpacking → re-scan + report (slop index, FKGL before/after, clarity edits, substantive questions for the author) | `apps/quality/review.py`, `prompts/review_{deslop,clarity,wordlevel}.md` |
| Final cleanup | clean-user-facing-text, then house-style mechanics (dashes, curly quotes, emoji, thematic breaks, escaped punctuation, spacing, `[HERO:]` cues), then the mechanical sweep. If `[VERIFY]`, `[SRC:]` or `[VISUAL:]` remain it **holds for review** and can't be approved; "Strip [SRC:] markers" helper | `apps/quality/house.py`, `executors.cleanup`, `services.strip_sources` |
| Publish | Refuses while markers remain. Excerpt → page Intro, chosen Tags → page tags; a quoted button label after the product link becomes a **CTA button block** | `executors.publish`, `apps/content/publishing.py`, `markup.build_article` |

Every rewrite (edit step, chat apply, Tune) passes `review.accept_rewrite`: headings kept, most words kept, **protected spans** (numbers with their unit, section/regulation refs, URLs, acronyms, markers) unchanged and **no negation lost** (unfolding "not X but Y" is allowed). Tune also refuses a drop over 1.5 grades that leaves sentences flat (≥ 70% in one length band, judged on ≥ 4 sentences).

### Also built this session

- Company CMS page types (fa78bbe), Settings › Default models per task, AI providers page.
- Steps can't start before their input is approved (model choice/Retry on a waiting step keeps it pending; approving the previous step starts it or restarts a failed next step).
- Timers: server-rendered elapsed (right on reload), live times in the step list, time in queue, "took" per step/version, slow-step warning.
- Audience profiles per region (Settings › Audience profiles; seeded B2B SaaS EHS, grade 8), fed to every prompt and the chat; the wizard pre-fills per region.
- Reading grade only on article steps (draft, review and edit, cleanup, localise): whole-article FKGL + sentence-length spread, then per-section rows (references, tables, notes not graded).
- Suggestions chat + Tune buttons on steps waiting for review (`apps/studio/assistant.py`, worker task `run_chat`); models in Settings › Default models (Suggestions chat, Section tuning).
- Send back with feedback (regenerate with a chosen model, or targeted edits through the chat); Reject the whole run; Reopen a rejected run (optionally regenerating with the reason).
- Logo on in-article images: editor uploads get the SDS Manager logo by `sds-hero-stock`'s `inner_logo.py` (corner and regular/negative version chosen to avoid clashes), with a **Logo position** choice (Automatic, top/bottom left/right) and an opt-out. Images chosen from the library aren't re-branded.
- Site-mapping eval (`tests/test_site_mapping.py`): a skill-style article renders every component; pages created directly under Root (as in the headless company CMS) have no public URL here, so listings and language links now skip them instead of printing `href="None"`.

### Things a new session must know

- Develop while share mode runs with one-off dev containers: `docker compose run --rm --no-deps -T web …` (bind-mounted code); share mode bakes the image, so `--build` it after changes.
- **Never write Python with backslashes through Bash heredocs** in this environment: `\n` turns into a real newline (it broke files several times on 2026-10-14). Write scripts with the Write tool into the scratchpad and run them with `python -I`.
- Tests switch the Search results step off by default (`tests/conftest.py`); mark a test `search_step` to keep it.
- Vendored skill files are byte-identical copies, except `internal-article-links.md`, which keeps only published rows (`apps/quality/vendor/README.md`); added on 2026-10-14: `ehs_seo_blog/data/{banned-words.tsv,internal-article-links.md,product-link-registry.json}` (lead-magnet-links.md is deliberately not vendored: it lists unreleased items from an internal tracker and the repo is public).
- `STUDIO_SECRETS_KEY` is in `.env`; back up `.env` separately.

### Restore point (taken 2026-10-14, before the SOP agent work)

If the next round goes wrong, go back to this state:
- **Code:** git tag `restore-2026-10-14` (= ee24d43, on GitHub). `git reset --hard restore-2026-10-14`, or check it out to compare.
- **Data and settings:** `D:\backups\studio-2026-10-14-ee24d43\` holds the database dump, the media archive, a git bundle of the whole history (works without GitHub) and a copy of `.env`, with step-by-step instructions in its `RESTORE.md`. The same dump and archive are in `./backups` (`latest.txt` = 20261013-213500 UTC).

### Next chat: the SOP agent for one-shot generation (agreed with the user)

The user's next task: turn the combined workflow knowledge into an agent with an SOP that adapts to whichever model is used, as the path to one-shot generation (brief in, publish-ready article out, with the same checks). Starting points:
- The knowledge is spread over `apps/studio/prompts/*.md` (`_rules.md`, research, outline, draft, review_*), `apps/quality/review.py` (edit sequence, fact protection, grade rules), `apps/quality/house.py` (house mechanics, markers), the audience profiles and the search step. The user's skills behind them: `~/.claude/skills/ehs-seo-blog-optimized/`, `deslop/`, `clarity-review/`, `sds-hero-stock/`.
- Keep the step-by-step pipeline working; one-shot is an additional mode. Plan it with the user first (plan mode), then build.

### Ideas the user raised, not built yet

- Sectional drafting (approve one H2 at a time), link_check / editorial_flow_check scripts from the skill, re-branding images chosen from the library.
- Run 12 ("management of change safety") is rejected; it can be reopened from its banner.

## What was built on 2026-10-13/14 (after M8)

| Commit | What | Where to read |
|---|---|---|
| 2fef876 | **SVG and WebP images**: SVG added to `WAGTAILIMAGES_EXTENSIONS`, served with a sandboxing CSP (`SvgSandboxMiddleware`, Caddy), rasterised by CairoSVG for DOCX | `docs/operations.md`, `tests/test_image_formats.py` |
| 45ee088 | **M9 phase 4**: Tiptap 3.31.3 editor in `frontend/` (vanilla JS, esbuild), Edit → Save as new version / Save and approve, Visual/Markdown, browser autosave + restore, `base_version` conflict check | `docs/ui-ux-plan.md` › Phase 4 |
| a097fa2 | **Provider keys in the admin** (ADR 0008): Settings › AI providers (superusers): set/replace/remove keys, add OpenAI-compatible providers (OpenRouter) and models; Fernet under `STUDIO_SECRETS_KEY` from `.env`; write-only, last-4 hint, history entries; `rotate_provider_keys` | `docs/security.md` › Provider keys, `docs/adr/0008-*` |
| bdf7c79 | **M9 phase 5**: Wagtail page/document/image choosers in the editor, upload by button/drag/paste (alt required), YouTube/Vimeo embeds (`WAGTAILEMBEDS_FINDERS`), `/` menu, writers get image/document add+choose | `docs/ui-ux-plan.md` › Phase 5 |
| 12d43c6 | **M9 phase 6**: word-level and rendered Compare, link tooltips and shortcut list in the editor, studio templates without inline styles, public article CSS for figures/embeds/FAQ/tags, draft-prompt FAQ aligned with the blog skill, end-to-end check through Publish | `docs/ui-ux-plan.md` › Phase 6 |

The Content Studio Handbook artifact (https://claude.ai/artifact/Cp91uDDbGKT2H2qqPa8Cn4, private) was updated on 2026-10-14 to match.

### Things a new session must know

- **`STUDIO_SECRETS_KEY` is in `.env`** (generated 2026-10-14). It encrypts admin-stored provider keys; database backups don't contain it. Back up `.env` separately. No keys are stored in the admin yet; all providers still use `.env`.
- **Share mode needs `--build` once**: the images changed (Node stage for the editor bundle, `libcairo2`, `cairosvg`, `cryptography`). Dev was rebuilt already.
- **Dev has a `frontend` service** (`npm ci && npm run watch`, node_modules in a named volume) that rebuilds `apps/studio/static/studio/editor/` (git-ignored) on changes. By hand: `cd frontend && npm run build`; tests: `npm test`.
- **Restart the worker after prompt changes**; the draft prompt changed on 2026-10-14 (done then).
- Built-in browser pane limits (for testing the editor): no animation frames, `<dialog>` close events don't fire, screenshots miss the dialog top layer, synthetic double-clicks don't select words. Check behaviour through the DOM (`form.studioEditor` is the editor instance).

## Restarting after the PC was off

Nothing needs to be re-generated: no step was queued or running at shutdown, and runs resume where they stopped. Data is in the Docker volumes on `D:\DockerData`.

0. `cd D:\workflow-generation-project` first: compose looks for its files in the current folder.
1. Start Docker Desktop (`D:\Docker\Docker Desktop.exe`) and wait for "Engine running".
2. Start Ollama from the Start menu (needed for the local `quality` models: outline, draft).
3. Start the studio in one mode (the dev image is built; **share mode needs `--build` once** after the 2026-10-14 changes, then only after code changes):
   - Shared over ngrok: `docker compose -f docker-compose.yml -f docker-compose.share.yml up -d --scale web=2 --scale worker=2`. The public URL is the same (`docker compose -f docker-compose.yml -f docker-compose.share.yml logs ngrok`).
   - Dev only: `docker compose up -d` (http://localhost:8000/admin/).
4. Check: `docker compose ps` (add the same `-f` files in share mode) shows db healthy, web healthy, worker and backup running; the dashboard's Services panel shows Ollama reachable. The `backup` service takes a backup on start.

Waiting for review (4 steps, unchanged since 2026-10-13; throwaway test runs 13–16 and page 6 were deleted): run 11 Research and run 12 Outline ("management of change safety"), run 10 Review and edit, run 9 Publish ([Live test]). The `[Example]` demo runs 5–8 were deleted on 2026-10-13 (briefs kept; backup `backups/db-20261013-120342.dump` taken just before).

## Start here

0. Next chat: plan and build the SOP agent for one-shot generation (see "Next chat" above). A restore point exists (tag `restore-2026-10-14`).
1. Score the outline evaluation (below), then set the default models.
2. Optional: install ComfyUI and export the workflow (`docs/setup.md` step 6) to test local hero images live.
3. Review run 9's article (page 5) before a moderator approves it: two claims are still marked [VERIFY], and its meta description says "30 days after last use federally" (OSHA's records rule talks about 30 years).
4. Put teammates into the four groups (Writers, Editors, Moderators, Operators) under Settings › Users.
5. Try the editor on a real step (Edit on run 11's Research or run 12's Outline) and say what to polish; optionally add an OpenRouter key and models under Settings › AI providers.
6. Copy `backups/` (and `.env`, separately) off the PC now and then; `D:\backups\docker-2026-10-13\` (manual backups from the disk-full incident) can be deleted once everything is confirmed working.
7. Optional: point the publish webhook at an n8n workflow (`docs/setup.md` step 7); move to a server with `docker-compose.prod.yml` when ready (`docs/deployment.md`).

## Where things stand

| Milestone | State | Commit |
|---|---|---|
| M1 Bootstrap (Wagtail 8 / Django 6.1, Docker: web, worker, db, migrate; CI) | Done | 4731851 … c6786ca |
| M2 AI provider layer + blind model evaluation | Built; **outline round complete (36/36), waiting for your blind scores** | c9e65a6 |
| M3a UX (wireframes: https://claude.ai/artifact/GjFjc7himFSZiHNYkKV9tw, copy in `docs/wireframes/`) | Done | 51ab651, 2c47c69 |
| M3b Content Studio screens in the Wagtail admin | Done | c84881e |
| M4 Background generation (worker runs steps, fallback, retry, notifications) | Done, verified live (run 9) | 67641ab |
| M5 Seven-part review-and-edit sequence + vendored skill scripts | Done, verified live (run 10) | 5df13ae |
| M6 Images (ComfyUI provider, vision check, sds-hero-stock branding) | Built, verified live on run 9 (Cloudflare + Gemini vision + branding); ComfyUI mocked | see git log |
| M7 Publish (ArticlePage, moderation, exports, n8n hook) | Built, verified live on run 9 (draft page 5 in Moderators approval; MD/HTML/DOCX/WebP exports); webhook mocked | see git log |
| M8 Hardening (roles, login protection, secret review, backups, production compose) | Built; see `docs/security.md` | see git log |

| SVG/WebP images | Done | 2fef876 |
| M9 UI/UX overhaul (dialect, article page, theme, editor, choosers, compare) | Done, verified end to end | eb5778d, 45ee088, bdf7c79, 12d43c6 |
| Provider keys in the admin (ADR 0008) | Done | a097fa2 |

Everything is pushed to `main`; CI (lint and tests, frontend, image build, secret scan) is green at 12d43c6.

## Evaluation (M2)

- Run folder: `eval/runs/r1-outline/` (git-ignored). **All 36 outlines are done (12 models × 3 briefs).**
- Reasoning settings, which matter when you interpret scores:
    - Qwen3.8 27B: reasoning on, all briefs.
    - glm-4.7-flash: reasoning off, all briefs (on, it returned empty output).
    - Qwythos 9B: reasoning off for `b1-sds-retention` only; the other two briefs ran with the model's default (on) before the empty output appeared. `eval/candidates.yaml` now has it off.
    - Ornith 9B: model default.
- Run long evals in a **one-off container**:
  `docker compose run --rm --no-deps -T web python manage.py eval_models --round outline --run-dir eval/runs/r1-outline`
  (an `exec` into `web` dies if the dev server reloads on a code error).
- Then score `eval/runs/r1-outline/scorecard.md` blind (open `key.json` only after), run `python manage.py eval_report eval/runs/r1-outline`, pick defaults, set `AI_PROFILES` in `config/settings/base.py` and `AI_PROFILES_INTERIM = False`.
- Later rounds: draft (best outline per brief in `eval/outlines/`), image, and edit (one draft per brief in `eval/drafts/`).

Verified free models: local Ollama (Qwen3.8 27B ~19 min/outline at 4.5 tok/s; glm-4.7-flash with think off; Ornith 35B-A3B; Ornith 9B; Qwythos 9B), Ollama Cloud free (nemotron-3-ultra/super, gpt-oss:120b, gemma4:31b), Gemini free (3.8/3.7 Flash; Pro has no free quota; 2.5 closed), Groq (gpt-oss-120b; qwen3.8-27b limited to 1,000 output tokens/min), Cloudflare images (flux-2-klein-4b, flux-1-schnell). NVIDIA NIM, Mistral and OpenRouter are not usable.

## M6 notes

- How the hero step works: `docs/workflow.md#hero-image-step-m6`. Code: `apps/studio/executors.py` (`hero_image`), `apps/quality/hero.py`, `apps/ai/images/comfyui.py`.
- Brand assets are git-ignored (ADR 0004). A fresh clone needs `docs/setup.md` step 5, or heroes come out unbranded with a note.
- No generative fill in the container (LaMa needs PyTorch). Strips up to 15% of the width get the skill's mirror fill (you accepted it on 2026-10-13; the veil is fully opaque there). Beyond that, a subject starting at 50% or more is branded as it is; further left, one more photo is generated, then you're asked to regenerate. FLUX tends to centre the subject (48–57% in the live runs).
- A `Headline:` regenerate note re-brands the same photo (no new image); used live to fix a too-wide subject box.
- Gemini 3.7 Flash returned HTTP 500 for several image requests; the Qwen3-VL 8B fallback worked but boxes subjects less tightly (it included furniture until the prompt excluded it).
- gpt-oss spends its token budget on reasoning: the hero prompt step needed `max_tokens` 3000 (600 returned empty text, and an empty prompt now fails the step).

## M7 notes

- How publishing works: `docs/workflow.md#publish-step-m7`. Code: `apps/content/` (`models.py`, `markup.py`, `publishing.py`, `exports.py`), the `publish` executor, and `run_export` in `apps/studio/views/runs.py`.
- Run 9's article is page 5 (`/home/articles/...`), a draft waiting in Moderators approval. Its text still has two `[VERIFY]` claims, and the meta description says "30 days after last use federally", which looks wrong (OSHA's records rule talks about 30 years). Check it before approving.
- Steps without a model (Final cleanup, Publish) have a **Run again** button while they wait for review. Once approved, a step can only be rerun from code (`status = queued` + `services.enqueue`).
- Localised variants are exports only; no second page is created (Wagtail i18n isn't enabled).

## Share mode (2026-10-13)

- `docker-compose.share.yml` + `deploy/Caddyfile`: production mode behind Caddy and an ngrok tunnel; `--scale web=N --scale worker=N` works. Details: `docs/deployment.md`, ADR 0005.
- Verified: the public URL (the ngrok account's free dev domain; see `docker compose logs ngrok`, not recorded here because the repo is public) serves admin, static and media through 2 web + 2 worker containers; login CSRF passes; `DEBUG` off.
- The ngrok authtoken is reused from the Windows (Store) ngrok agent config via `NGROK_CONFIG_FILE` in `.env`; it's never copied anywhere.
- Docker's disk moved to `D:\DockerData` after C: filled up and Docker kept trying to reformat its disk (see operations.md › Disk space). Backups from that day: `D:\backups\docker-2026-10-13\` (SQL dump, media archive, every volume).

## M8 notes

- Roles: `apps/studio/permissions.py`, groups from migration `studio.0004_m8_groups`; enforced in views and `permissions.can_act`. Superusers bypass.
- Login lockout: django-axes 8.3.1 (declares Django 6.0 support; tested on 6.1). Unlock with `axes_reset_username`.
- Secrets: `apps/ai/redact.py` runs on every `ProviderError`, failed-step error and log line. CI job `secret-scan` runs gitleaks over the full history.
- Backups: `backup` service in `docker-compose.yml` (`deploy/backup.sh`), nightly into `./backups`, 14 days; restore into a scratch Postgres tested.
- Production: `docker-compose.prod.yml` + `deploy/Caddyfile.prod` (automatic HTTPS, HSTS); routes shared with share mode in `deploy/caddy/routes.caddy`. Validated, not run on a real domain.
- Shell gotcha: a backslash before `b` or `n` in Windows paths inside `python - <<EOF` snippets became a control character twice; write such text with the Write tool or a script file.

## Gotchas learned

- **Never write regexes or Windows paths through `python - <<EOF` in Bash**: backslashes become control characters or get eaten (happened four times on 2026-10-13). Write code with the Write/Edit tools or a script file in the scratchpad, and grep for control characters afterwards.
- Git Bash rewrites `/tmp/...` and `/backup` in `docker` arguments into Windows paths; prefix with `MSYS_NO_PATHCONV=1`.
- The dev stack is running at the end of this session (`docker compose up -d`, http://localhost:8000); share mode was stopped. Start share mode again with the command in deployment.md when needed.
- Previewing the admin in the built-in browser without typing a password: create a session with `django.test.Client().force_login(user)` in `manage.py shell`, then set the `sessionid` cookie on localhost:8000 via JavaScript.

- textstat needs NLTK's `cmudict` and, for English, crashes instead of falling back when it can't download it at runtime (NLTK 3.10.3's downloader can also reject its own temp file). The Dockerfile now bakes `cmudict` into `/opt/venv/nltk_data` with a SHA-256 check, and `nltk`/`pyphen` are pinned. On 2026-10-13 this left a research step stuck in Running in share mode.
- Anything after an executor returns (saving the version, metrics) is guarded: a metrics failure keeps the output (`metrics_error` in the version metrics), and a save failure marks the step Failed.

- Django 6.1 needs `django.contrib.postgres` in `INSTALLED_APPS` (Wagtail search on Postgres).
- pytest must use `--ds=config.settings.test` (containers set `DJANGO_SETTINGS_MODULE`); test settings use DummyCache, `STUDIO_EXECUTE_STEPS=False`, `STUDIO_QUALITY_SCANS=False`.
- The openai SDK 3.x bundles `httpx2`; tests inject a mock transport through `openai_compat.http_client_factory`.
- Groq rejects Python's default User-Agent (403); every request sends `AI_USER_AGENT`.
- Wagtail's `--w-color-*-50` tints don't switch in dark mode; the studio CSS mixes tints from foreground colours.
- Selects size to their longest option; panel controls are constrained to 100% width.
- Vendored skill scripts are excluded from ruff and must stay byte-identical (re-copy from `~/.claude/skills` to update).
- The `worker` container (db_worker) does not reload code or cached prompt templates: `docker compose restart worker` after changing executors or prompts.
- Docker Desktop must be started manually (`D:\Docker\Docker Desktop.exe`). Your admin user is `sdsmanager`.
