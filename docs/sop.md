# The content SOP and the self-reviewing pipeline (autopilot)

This is the standard operating procedure the studio runs an article through, written so that a person, a Claude Code session or any model can follow it. The studio enforces it in two ways: the step prompts (`apps/studio/prompts/`) tell each model what to produce, and the **SOP self-review** (`apps/studio/sop.py`, rubrics in `apps/studio/prompts/sop_rubrics.md`) checks each output against the same rules and sends it back to the model until it passes. In **autopilot** a run goes from brief to a draft page in Wagtail moderation on its own, stopping only where a step can't meet the SOP or a `[VERIFY]` claim needs a person.

The SOP distils the owner's Claude Code skills (`ehs-seo-blog-optimized`, `ehs-outbound-blog`, `deslop`, `clarity-review`, `clean-user-facing-text`, `sds-hero-stock`) and the two briefing prompts used with them. Where this file and a skill disagree, the skill is the source and this file is the bug.

## 1. Inputs (the brief)

| Field | Blog (sdsmanager.com) | Guest post |
|---|---|---|
| Topic, primary keyword, secondary keywords | Required | Required (title kept verbatim from the sheet; keyword and supporting keywords from the sheet) |
| Region | Required: sets regulators, spelling, examples, link slugs | Required too. Guest posts are not region-agnostic |
| Reading grade (FKGL) | Soft target, from the region's audience profile | Soft target; the host's range is recorded beside it, never replaces it |
| Audience, reader's expertise | From the audience profile, narrowed by the brief | Inferred from topic, site and intent if unset |
| Target length | A guide, calibrated to what ranks | The sheet's count as a baseline; longer where the SERP depth needs it |
| Call to action | Subtle link or button; the target is always a product page | None (informational, non-promotional) |
| Target site, site URL, narrative mode | – | Required; the site crawl proposes the narrative mode |
| Anchors | – | `anchor text | product URL` pairs in the sheet's order, each a different product page |
| Brief source | – | e.g. "Guest Post Plan sheet, row 14" |
| Notes | Angle, sources, things to avoid, host requirements | Host requirements from the sheet's Notes column (language variant, length rules, evidence standard) |

Standing rules that apply to every brief:

- **Regulation-light by default.** Cite the specific parts of a regulation that the supporting search queries and the ranking pages' structures call for, where they settle a reader's question. Never a tour of the statute. Completeness means answering what people search for.
- **Standard words over "simpler" ones.** Prefer the clearer, commonly used term even when it raises the grade. Lower the grade by syntactic unpacking (agent and verb for abstract subjects, split stacked clauses, gloss in place), never by uniform short sentences or synonym swaps.
- **No metaphors, no meta narration.** The only allowed self-reference is the intro's scope sentence with the literal words "this article" (or "walk you through … this article").
- **No invented regulations, figures, quotes or URLs.** A URL may be used only if it appeared in the search results, the research, or the vendored internal index. Unconfirmed claims carry `[VERIFY]`; sourced figures carry `[SRC: url]` until sign-off.
- **House mechanics:** no em or en dashes, straight quotes, Title Case headings, 3-4 line paragraphs, no emoji, no horizontal rules, no promotional voice.

## 2. Steps and what each must deliver

| Step | Deliverable | Deterministic checks (`sop.check`) | What the reviewer reads for (`sop_rubrics.md`) |
|---|---|---|---|
| Search results | Top results for the keyword in the region, autocomplete, each page's outline, length and grade | – (no model) | – |
| Site crawl (guest posts) | Site profile table: narrative mode, voice, headings, length, reading level, links, spelling; recommendations; notes | `## Site profile` with at least 4 rows; mechanics | Dominant pattern, not one page; surface only, never depth |
| Research | Search Intent · What Ranks · Must Include · Missing Opportunity · Keyword Table · **Regulation Depth** · **Anchor Opportunities** · Questions Searchers Ask · Sources · Claims · Common Misconceptions · Cannibalization · **Questions for the Requester** | All sections present; keyword table ≥ 3 rows; 8-12 questions (advisory); ≥ 3 claims; cannibalization verdict names a route; primary keyword present; mechanics | Intent → depth; regulation depth light; URLs only from inputs; every claim has source and status; cannibalization says what the existing article already covers |
| Outline | Search Intent · H1 Options · Detailed Outline · Intro Plan · Conclusion Plan · FAQ Plan · Claim Verification Table · **Keyword and Anchor Map** · Structure Decisions · Headings-Only Outline | All sections; headings-only block is `H1:`/`H2:`/`H3:` lines, `H2: Key Takeaways` second, verb-first CTA heading before `H2: Frequently Asked Questions` last with 3-7 `H3:`; ≥ 3 body H2s; keyword in an H1 option; no generic close; mechanics | Format matches what ranks; first H2 answers the primary query; H3 necessity test; title's questions in the first 30%; every fact one home; depth follows Regulation Depth and Cannibalization; anchors never adjacent; conclusion plan names gap, action, product page |
| Draft | H1 · intro · Key Takeaways · body · verb-first CTA conclusion · FAQ (`:::faq`) · References · metadata options (3 each: meta title, description, slug, tags, excerpt) | One H1 with the keyword; keyword in the first 100 words and a heading; "this article" scope sentence; 4-7 intro sentences (advisory); Key Takeaways first H2 with 3-7 standalone bullets (no pointers, no coverage framing); FAQ 3-7 questions, no links, no bare Yes/No; no generic close; sdsmanager.com anchors never adjacent; each brief anchor exactly once (guest posts), none in the close; no meta narration; keyword density ≤ ~2%; length vs guide (advisory); ≥ 3 internal links for a blog (advisory); mechanics | Intro order (example or pain point → why it matters → snippet → scope); answer-first headings; regulation only where it settles a question; `[SRC:]`/`[VERIFY]` discipline; second person, standard words; capsules; conclusion = gap, action, product; FAQ mirroring; metadata limits |
| Review and edit | The edited article: scan → deslop rewrite → clarity rewrite → grade tuning → re-scan, with notes | Same as the draft (without metadata) | Draft rubric still holds; protected spans and negations survived; machine-prose signatures gone; referents named; grade by unpacking only |
| Final cleanup | Hidden Unicode removed, house mechanics fixed, sweep run | Holds while `[VERIFY]`, `[SRC:]` or `[VISUAL:]` remain | – |
| Hero image | Prompt → photo → vision check → branded hero | Branding script flags | – (a person checks safety and text) |
| Localise (optional) | The regional variant with notes | Same as the draft (without metadata) | Everything belongs to the target region; changed facts carry `[VERIFY]` |
| Publish | Draft `ArticlePage` in Wagtail moderation; exports | Refuses while markers remain | – |

## 3. The self-review loop

For every step with **SOP self-review** on (all text steps in autopilot):

1. The step's model produces its output as usual.
2. House mechanics a script fixes better than a model are fixed first (`house.mechanical_fix`: em and en dashes, curly quotes, emoji, horizontal rules, spacing) and logged as "auto-fixed". Then `sop.check` runs the deterministic checks. Each finding is `block` or `advise`.
3. The **SOP reviewer** model (Settings › Default models › SOP reviewer; the `edit` profile by default) reads the rubric for the step, the brief, the audience profile, the inputs the step worked from (the search results and internal index for plans, the research and outline for the draft, the draft for the edit), the check results and the output, and answers `VERDICT: PASS` or `REVISE` with numbered **Findings** (where, which rubric rule quoted, the fix) and **Suggestions** (improvements that break no rule; they never block). It never rewrites, and a REVISE with no findings counts as PASS.
4. If the verdict is PASS and nothing blocks, the step passes. With its gate off it continues on its own; with the gate on it waits for you, with the log attached.
5. Otherwise the **step's own model** applies the blocking checks and the reviewer's findings as a targeted revision, changing nothing else and inventing nothing (a missing source becomes `[VERIFY]`, never a made-up URL). The revision is used only if it keeps every heading, most of the words and (for article steps) every protected span and negation. A refused revision is logged; the next round reviews the unchanged text and tells the model why its revision was refused.
6. Steps 2-5 repeat up to `STUDIO_SOP_MAX_ROUNDS` revisions (default 3, `.env`; the live runs needed a third round for plans; 2 is cheaper). A step that still doesn't pass **holds for your review** whatever its gate setting, with the open findings in its notes and the whole log on the run screen.

Cost: one generation plus, per round, one reviewer call and one revision. A step that passes first time costs one extra call. On gpt-oss:120b (Ollama Cloud) a research step with a full two-revision loop took about 50 seconds in the live test.

What the first live runs showed (2026-10-14): the loop cut the reviewer's findings from 10 to 2 over three rounds, fixed mechanics the model couldn't, and caught a fabricated statistic the model had slipped into the claims ("reduces reading time by up to 30%, based on internal testing"), which is exactly the kind of thing that must reach a person. The remaining finding at the hold was a formatting rule (questions not marked body or FAQ), which a third round would likely have cleared.

## 4. Where autopilot stops, by design

- A text step that can't pass the SOP within the rounds (open findings listed).
- The reviewer model failing (rate limit, outage): the output is kept and the step holds.
- Final cleanup, whenever `[VERIFY]`, `[SRC:]` or `[VISUAL:]` markers remain. Checking claims and sources is a person's job; strip `[SRC:]` from the cleanup screen once checked.
- The hero image, if its gate is on (the default in the wizard table; untick it to let autopilot continue).
- Publish creates a draft page in Wagtail's moderation workflow; a moderator still approves it. Nothing goes live from the studio.

## 5. How to run it

- **Wizard:** New brief → fill the brief → under Pipeline choose **Autopilot (one-shot)**. The SOP self-review column is ticked for every text step and the approval boxes are cleared; change either per step if you want to look at something anyway.
- **Briefs list:** **Autopilot** next to a saved brief starts the same configuration with the default models.
- **Reviewing a held step:** the run screen shows the **SOP self-review** panel (rounds, verdicts, check findings, reviewer findings, whether each revision was used). Approve, edit, send back with feedback, or regenerate as usual.
- **Tuning the SOP:** rubrics in `apps/studio/prompts/sop_rubrics.md` (one `## step` section each), checks in `apps/studio/sop.py` (`check_*` functions; tests in `tests/test_sop.py`), reviewer and revision prompts in `prompts/sop_review.md` and `prompts/sop_revise.md`. Restart the worker after changing prompts.

## 6. Model-agnostic by construction

The reviewer is told the rules, not trusted to know them: the rubric, the check results and the inputs travel with every call, so a small local model and a large cloud model get the same contract. Deterministic checks catch what a weak reviewer misses; the revision guard (`accept_rewrite`) catches what a weak writer breaks. Pick the models under Settings › Default models: a fast model for the reviewer is usually enough, because the rubric and the checks do the work; the step's own model does the revision so the voice stays consistent.
