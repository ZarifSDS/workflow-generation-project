# SOP audit against the skills (2026-10-14)

The question: why does the autopilot keep misfiring (holding, looping, deadlocking, or passing something wrong), and how do we remove misfires by design instead of finding them one live run at a time?

Method: five read-only audits, each reading one skill in full (SKILL.md, every reference, the data files and scripts) against the studio code: `ehs-seo-blog-optimized` (blog path), `ehs-outbound-blog` (guest-post path), `deslop` + `clarity-review` (Review and edit), `sds-hero-stock` (hero), and an internal-consistency audit of the SOP loop itself (`apps/studio/sop.py`). Every high-severity claim below was re-checked against the code; most were reproduced with a script. About 70 findings came back. They reduce to six root causes.

## The six root causes

### 1. The guard doesn't know what a finding asks for

The loop is: checks and reviewer produce findings, the model revises, and a guard (`sop._guard`, `review.accept_rewrite`) decides whether the revision may be used. The guard enforces fixed invariants (keep every link, every heading name, every negation, every protected span), whatever the finding was. So any finding whose fix *is* one of those changes can never be satisfied: the step burns its rounds and holds. Today's live misfires were all this class (keyword in an H2 vs renamed headings; pointer sentences vs keep-every-link), and the audit found many more of the same shape:

- Bare "No," FAQ opener → the fix drops a "no" → refused as a lost negation.
- Negative parallelism ("isn't about X, it's about Y") → deslop's own fix drops a negation → refused.
- Link-placement blocks (two links in a sentence, one link per section, link-only sentence, adjacent sections, link in an FAQ answer, article in the close) → every fix removes a URL → refused.
- A plan section named "Keyword & Anchor Map" or "Cannibalisation" → the fix is a rename → refused.
- Adding Key Takeaways and renaming a generic close in one revision → section count changes → refused.
- Localise: replacing OSHA with HSE or `/us/` with `/uk/` → protected span → refused, though the rubric demands it.
- Protected spans are "number + next word", so "1910.1200 requires" is a span and *any* rewording after a regulation number is refused. In the edit step one refused span discards the whole article's deslop or clarity pass, not just that sentence.

**Design fix: findings carry their permissions.** Each `Finding` states what its fix may change (`may_drop_urls`, `may_rename_heading`, `may_drop_negation_in`, `may_change_spans`, `may_drop_section`). The guard allows exactly the union of the permissions of the findings sent, and nothing else. Then it re-runs the checks on the revision: a revision that introduces a new kind of block is refused (no whack-a-mole), a revision that leaves the same blocks ends the loop early, and on a hold the best round's text is kept, not the last. Edit-step acceptance becomes per section (keep the accepted sections, revert only the refused ones), and protected spans become the number plus a real unit from a whitelist. This removes the deadlock class by construction instead of one pair at a time.

### 2. One shape for every content type

The checks, the writer prompts and the rubrics were written for the sdsmanager.com blog, and other types get a few rules added on top or a block turned into an advisory. That leaves contradictions the loop can't resolve:

- **Guest posts:** the outline step has no guest-post branch at all (Key Takeaways second and FAQ last are hard blocks; "no H1 option carries the keyword" blocks even though the sheet title is kept verbatim). The "this article" scope sentence is a block on every type, while the outbound rubric bans it. Draft prompts require Key Takeaways, FAQ, References and a product-page CTA; the outbound rules forbid a product link in the close; the close check reads the last section (usually References), so it almost never fires; nothing stops extra sdsmanager.com links beyond the brief's anchors; a landing-page anchor URL also counts every module URL under it, so "exactly once" can block forever.
- **Localise:** the keyword checks use the source keyword while the prompt translates it; allowed URLs come from the base region, so a correct `/uk/` link counts as invented; the reviewer sees the draft, not the edited text localise worked from.
- **Lead magnets, whitepapers** get blog blocks (scope sentence, Key Takeaways first).

**Design fix: one check profile per content type**, kept in `types.yaml` (components that exist, heading case, scope sentence, keyword-in-H1 rule, link rules, close rule, metadata), read by the checks, the step prompts and the rubric assembly alike. One source for each rule means a prompt can't ask for what a check forbids. Guest posts get their own outline and draft branches (verbatim title, no blog components unless the host uses them, anchors only); localise gets a context built from the target region and the translated keyword.

### 3. Things a script can fix are left to a model round

Each model round costs a call, can introduce new problems, and may be refused. Many findings are mechanical:

- `claim. [VERIFY]` placement (the citation check couldn't see it; **fixed today**).
- Marker variants (`[VERIFY at publication]`, which the outbound rubric itself prescribes, escaped the publish guard; **fixed today**).
- Section-name canonicalisation (`&`/and, British/US spelling, FAQ/FAQs, Sources/References, metadata headings).
- URL canonicalisation (trailing slash, `www.`, region slug).
- Unlinking a link inside an FAQ answer, wrapping an unfenced FAQ, comma→colon in a plain heading.
- Running the house mechanics on the *revision* before the guard compares it (today a model's `10–15` against the fixed `10-15` reads as a changed span).

**Design fix: mechanical first, everywhere.** Every deterministic repair runs before each check round and on every revision before the guard. A model round is spent only on judgment.

### 4. The reviewer is asked to judge what it can't see, and told advisories are verified

The reviewer prompt says to treat check results as true and that they "count against a PASS", and the list includes every advisory and heuristic flow prompt (which the skill itself calls "prompts to read, never a gap to close"). The reviewer turns them into findings, and the reviser then "fixes" correct text. Several rubric lines depend on data the reviewer isn't given: the measured reading grade, the product registry and internal index on the draft, the site profile on every guest-post step, the full draft (truncated at 2,500 words) for "protected spans unchanged".

**Design fix:** two lists to the reviewer, "Blocking (verified)" and "Prompts to read (candidates, often false; at most a Suggestion)". Every rubric line is either backed by the data it needs (pass the grades, registry, index, site profile) or turned into a deterministic check and removed from the rubric. The reviser gets the concrete value a finding needs (the outline's product URL, the allowed subsections, the brief notes).

### 5. Checks that fire on correct text

False positives are the other half of the misfire problem. Confirmed examples:

- The pointer-sentence pattern matches "refer to the SDS for the PPE it lists".
- The coverage-framing pattern matches "Section 8 covers exposure controls" in Key Takeaways.
- The meta-narration pattern matches "the PPE named in this section", meaning SDS Section 8.
- The comma rule matches "If an SDS Is Missing, What Should You Do?" and "1,000 Chemicals". It was my own addition today and isn't in the skill.
- Keyword stuffing counts FAQ questions and acronym-only matches, so an SDS article with natural headings blocks.
- Keyword density counts "sds" inside `sdsmanager.com` links.
- The close-must-link-a-product check (also mine, today) contradicts the skill's "No honest fit, no product".
- The adjacent-anchor rule is a guest-post rule applied to blogs.
- The vendored `link_check` heuristics ("for more", four words or fewer) were mapped to blocks.
- The reading grade counts headings and unpunctuated list items as sentence parts. One verified example read 9.2 instead of 7.1, so list-heavy sections are queued for tuning.

**Design fix: calibrate every check against fixtures, the skill's own method.** The blog skill's maintenance rule is:

- **Fixture A**, a finished, editorially approved article, must produce zero failures that describe no real defect.
- **Fixture B**, a deliberately bad draft, must have every defect caught.

That is a finite, deterministic test, not an endless stress run. Every check gets both fixtures; a check that fails Fixture A is loosened or demoted to a prompt, and one that misses its Fixture B defect is tightened. In addition, a **replay harness** runs the current checks, offline and with no models, over every version stored from runs 17 to 21. It reports each block with its text, so a change to a check shows its false-positive and catch counts before any live run.

### 6. Data and vendored code drift

- The vendored internal index still listed 11 rows the skill marks as returning 404 (planned slugs): the studio offered them as checked link targets. **Removed today.** Because the file was committed earlier today, those planned slugs are in the public repository's history.
- The SDS Manager chemical-management product pages aren't in the product block, so an SDS-topic article has no honest CTA target except from memory (which the URL check then blocks).
- Lead magnets: not vendored (by choice, the file lists unreleased items); `/content-library/` isn't recognised as a lead-magnet path, so a lead-magnet CTA from the search results would pass the "never a lead magnet" rule.
- Hero: the vendored `hero_compose.py` and `svgify.py` are older than the skill's (the line-colour rules are missing); `lama.py` is a deliberate local fork.
- `ehs-outbound-blog/references/voice-and-style.md` lines 173-175 are corrupted in the skill itself (a sentence cut mid-word with a registry row spliced in).

**Design fix:** a vendor manifest (file → skill path → hash, with intentional forks listed) and a test that fails when a vendored file drifts or a not-live row reappears.

## Edit step specifics (deslop, clarity-review, grade tuning)

- **Why FKGL stays near 13:** FKGL = 0.39 x (words per sentence) + 11.8 x (syllables per word) - 15.59. EHS prose runs at about 1.7 syllables per word. Reaching 9 at that vocabulary needs about 11.6 words per sentence, and the user's rule keeps the standard words. So the target can only be met with uniform short sentences, which is the banned move and produces "The operator… The operator…".
- **The skill already allows for this:** domain vocabulary "sets a floor, so the piece may land a grade or two above target". **Fix:**
  - compute a per-section vocabulary floor and tune toward max(target, floor);
  - list the actual stacked sentences for the model to unpack;
  - refuse rewrites that create runs of sentences opening with the same subject;
  - grade without headings, and with list items terminated.
- Structural scan findings (rhythm, sentence construction) go into the automatic rewrite, but deslop says to surface those for the author, not apply them. Their text also arrives garbled (the code reads a `message` key the script doesn't emit).
- The scanners' own fix guidance (class-A replacements with conditions, class-B "no synonym swap") is dropped, and low-severity findings are sent too.
- The deslop prompt collapses tricolons with no exception for a list a regulation enumerates, so regulatory list items can be deleted.
- `frame_scan`'s term-drift output is read under the wrong key and never used.
- The edit report shows clarity edits even when the rewrite was refused, and nothing re-scans after the SOP loop changes the text.

## Hero specifics

- The generated photo is 1440x816, not 16:9, so a full-height subject leaves a grey stripe the flag misdescribes; centre-crop to 1440x810 first.
- A failed or truncated vision check, or an unusable subject box, never holds, so text and safety go unchecked. Hold on "unchecked".
- Placeholder items ("None") hold needlessly, and safety items have no severity.
- The headline is the meta title, not the H1 the skill specifies.
- The stale `hero_compose.py` lacks the one-colour-per-line rule.
- WebP and layered SVG outputs are discarded.
- On a guest post the SDS Manager branding shouldn't apply at all.

## The content-editing skill and the SOP agent

The owner's lightweight editing skill (`content-editing`, distilled from Ryan Law's *How to Edit*; kept at `D:\ai-memory-vault\skills - zipped\sds-manager\SKILL.md`) works well in practice. The owner restated the goal: the SOP is an **agent in the backend that guides the content workflow**, not only a set of checks. The skill fits that goal better than any single rule. Its core is an orchestration rule rather than an editing rule: **work top-down (strategic, then structural, then line), and never polish sentences before strategy and structure are sound.**

Where it maps onto the pipeline:

| Skill | Studio step | Already there | What it adds |
|---|---|---|---|
| Step 0, acquire context (strategy, outcome, audience, scope); read the whole piece first | Brief, audience profile, every reviewer call | Brief and audience reach every prompt | The reviewer reads the whole piece: today the draft is cut at 2,500 words for review_edit, against "read the entire piece before any edit" |
| Strategic edit: will this solve the problem (intent, can it rank)? If not, stop | Research (Search Intent, What Ranks, Cannibalization) and the outline approval | The analysis exists | A **stop**: a strategic failure (intent mismatch, cannibalization with no distinct angle) holds before the outline instead of being polished downstream |
| Structural edit on the 30% outline: thesis, MECE, Chekhov's gun, zoom in, reader's draft, parallel and high-concept headers, 80% how, weighted word counts | Outline step and its SOP review | Bullets and word counts per section, structure decisions, answer-first first H2 | An article-level **thesis**; promises in the title, intro and headings paid off; out-of-scope sections cut (run 20's first H2 "What Is an SDS and Why It Matters" in a how-to is the skill's own example of a "why X matters" section); headers in parallel form |
| Reverse-outline a full draft before judging it | Draft and Review and edit | None | A **deterministic reverse outline** (headings, first sentence and words per section) compared with the approved outline: missing, extra or reordered sections, weight drift and unpaid promises are structural findings that need no model |
| Line edit: weasel words, BLUF, steelman, reader feels smart, no armchair claims, dense words, varied rhythm, facts verified | Review and edit (deslop, clarity, grade tuning), draft rubric | BLUF = answer-first; vague attribution and filler in deslop; `[VERIFY]` for facts | "Five whys" on weasel words with `[VERIFY]` (the skill's `[NEEDS: …]`) where the answer isn't in the research; steelmanning, mainly for guest posts and thought leadership |
| Write 20 titles, shortlist 3-5 | Metadata options (3 titles) | Three options | Generate wide, then shortlist |
| Editing AI drafts: structure and format, tone and voice, accuracy | The whole autopilot | All three, as separate steps | Nothing new |
| Feedback: inline comment with why and an example rewrite; an overview of 1-3 themes; edits invite pushback | Reviewer findings and the hold notes | Findings say where, which rule and the fix | An **example rewrite** in every finding, so the reviser aims at a target instead of guessing; the hold note leads with the 1-3 themes a person should look at |

Where it doesn't apply: house mechanics, markers, the hero, publishing, localisation.

Two points need care:

- "Dense words" ("easy to use" becomes "intuitive") and "vary sentence structure" sit beside the owner's rule of standard, clearer words over "simpler" ones. Density is welcome where the denser word is also the standard one. Rhythm variation is the last polish, never a grade-tuning device.
- "High-concept headers" (benefit and advice) and the blog skill's question-shaped H2s agree for how-to content. For definitional queries, the search query wins.

### How it changes the agent: findings carry a level, and the level decides the route

Today every finding at every step becomes a revision of that step's text. That is why structural fixes (add, drop, reorder or rename a section) reach a line-level reviser and are refused by a guard built to protect structure. The editing hierarchy gives the routing:

| Level | Example | Route |
|---|---|---|
| Strategic | Intent mismatch; the article cannibalises one that already covers the angle | Hold for a person before the outline is approved; never revised by a model |
| Structural | Section missing, out of scope or out of order; promise not paid off; weights off; first H2 not the answer | At the outline step, revise the outline. At the draft step or later, **send back**: regenerate the draft from the outline with the finding as the note, or revise the outline first if the outline is the cause |
| Line | Wording, BLUF inside a paragraph, weasel word, link placement, FAQ opener | Targeted revision of the text, with the guard permissions from cause 1 |
| Mechanical | Dashes, markers, names, URLs | Script, before any model round |

The agent then guides the workflow instead of looping on one step: it decides per finding whether to fix in place, send back to an earlier step, or stop for a person, and it never spends line-level rounds on a piece whose structure is wrong. The deterministic reverse outline makes the structural level cheap and model-free on drafts. Together with finding-scoped permissions (cause 1), this is the agent design: **classify, route, then allow exactly the change the route needs.**

## Plan, in order

| Phase | What | Removes |
|---|---|---|
| 0 (done today) | Not-live rows removed; every `[VERIFY…]` form held at publish; `[VERIFY]` kept inside its sentence | Wrong publishes |
| 1 | Fixture A/B per check + the replay harness over stored runs; record today's baseline | Lets every later phase show its effect without live runs |
| 2 | Findings carry a level (strategic, structural, line, mechanical) that routes them (hold, send back, revise, script) and the permissions their fix needs; revisions re-checked (no new block kinds, early stop, best round kept); deterministic reverse outline of drafts against the approved outline; per-section edit acceptance, unit-whitelist spans, per-sentence negation rules, mechanics on revisions | The whole deadlock class (cause 1) and structural fixes forced through line revisions |
| 3 | Check profiles per content type in `types.yaml`; guest-post outline/draft/edit branches; localise context | Contradictions (cause 2) |
| 4 | Remaining mechanical fixes (section names, URLs, FAQ unlinking, heading variants) | Model rounds spent on mechanics (cause 3) |
| 5 | Two-tier reviewer input; data-backed rubric lines only; reviser gets concrete values | Invented findings (cause 4) |
| 6 | False-positive fixes, each proven on the fixtures and the replay | Cause 5 |
| 7 | Edit step: vocabulary floor, stacked-sentence targeting, repetition test, scanner guidance, frame_scan fields | Flat prose, edit refusals |
| 8 | Hero fixes; vendor manifest and drift test | Cause 6, hero misfires |

### Phase 1 (done): the instruments and the baseline

- `python manage.py sop_replay [--runs …] [--steps …] [--latest] [--out file]` (`apps/studio/replay.py`) runs `sop.normalise` and `sop.check` (exactly what the loop does before its reviewer, now one shared function) over stored versions and writes a Markdown report: firings per check (`sop.check_kind` groups findings by check), examples to read, and per-text block counts with what was auto-fixed.
- `tests/test_sop_fixtures.py` with `tests/fixtures/sop/` (README there):
  - Fixture B (`b/blog_bad_draft.md`) plants one defect per blocking check. All 16 are caught, and any block it doesn't declare fails the test, so a new false positive shows up at once.
  - Five planted defects nothing deterministic catches are listed as known gaps and printed on every run: vague attribution, tidy wrap-ups, puffery outside the banned list, a local run of flat sentences, and an unsourced statistic. Deslop's lexical scan has no patterns for the first two.
  - Fixture A (`a/`) waits for owner-approved articles. It requires zero blocks.
- **Baseline** (latest version of each step, runs 18 to 21): 13 texts, 44 blocking findings, 7 texts with none. Every plan text is clean. The blocks sit in drafts and edits: comma-for-colon headings 24, an invented URL 6, a close with no product link 4, pointer sentences 4, adjacent anchors 2, one link per section 2, link-only sentences 1, meta narration 1.
- What the replay settled: the comma rule's 11 distinct headings are all real topic-qualifier commas ("Worked Example, Acetone SDS"). Narrowing it for questions, digit groups and headings that already have a colon changed no firing.
- It also found a prompt-induced artifact: a heading containing the literal `++underlined text++`, copied from `_rules.md`'s list of spans to keep. That goes to phase 4 (mechanical fix plus clearer wording in the rule).

### Phase 2 (done): findings carry a level and permissions; Fixture A calibrated the checks

- **Findings carry permissions.** Each `sop.Finding` has a `level` and an `allows` dict:
  - `drop_urls` for invented URLs, pointer sentences, FAQ links, link-check placements and an article in the close;
  - `rename` for the keyword-in-heading, comma, generic-close and tacked-on-keyword checks;
  - `drop_negations` for a bare "No," FAQ opener;
  - `drop_spans` for an unsourced citation.
  The guard (`sop._guard`, `review.accept_rewrite`) allows exactly the union of what the findings sent allow (`sop.permissions`).
- **Every revision is normalised and re-checked.** One that adds firings of any check is refused as "it introduced new problems" (`sop.introduced`). The loop stops when the reviewer passes and the blocks didn't move, and on a hold it keeps the best round's text.
- **Routing by level.** Structural blocks in an article (Key Takeaways missing or misplaced, no FAQ, H1 count) aren't sent to the line reviser. The draft and the localised variant are regenerated once, inline, with them as the regenerate note, and the better result is kept (`sop._send_back`). A strategic finding holds without a revision (no check produces one yet; the reviewer will in phase 5).
- **Reverse outline** (`sop.check_reverse_outline`, advisory, structural): planned H2s missing from the draft, or out of order, against the approved outline. On runs 18-21 it fires once, on a real change (run 20 replaced the outline's "What Is an SDS and Why It Matters" with an answer-first H2).
- **Plans.** Near-miss section names are matched to the required ones mechanically (`canonical_section_names`). Bold labels become sections only when they name a required section, so "**Regulatory claims**" inside Claims no longer splits it.
- **Edit step.** Rewrites are accepted section by section (`review.accept_by_section`): a section that changed a fact or lost a negation reverts alone, and the notes say which. A number protects its unit, not the next word ("1910.1200 requires" can become "Under 1910.1200, employers must"). Numbers written out are protected too: "thirty years" turning into "ten years" used to pass. Deslop's negative parallelism may unfold.
- **Fixture A** (owner's picks; tests/fixtures/sop/):
  - the published JSA (US) and WHS (AU) blogs, committed;
  - three approved guest posts (life sciences, UK risk registers, HazCom training), kept in `a_local/`, which is git-ignored because they aren't published.

  They raised 21 blocks before calibration and raise none now:

  | Check that misfired | Calibration |
  |---|---|
  | Keyword "stuffing" (the JSA blog has it in 17 headings) | Blocks only the tacked-on shape from run 20: the same connective plus keyword ending three or more headings |
  | FAQ count (the JSA blog has 8) | Advisory |
  | Adjacent sdsmanager.com sections | Guest posts only: both blogs do it (owner decision 2, answered by the data) |
  | More than one internal link per section | Advisory |
  | Bare Yes/No | Blocks only when the answer doesn't restate the question's subject: "Yes, WHS risk management applies…" is fine |
  | Guest posts: keyword in the H1, the "this article" sentence, keyword in a heading | Not required |
  | Anchor counted twice | Counted by exact URL: the landing page `/uk/` is a prefix of module pages |
  | Intro of an H3-only article read as the whole text | The intro ends at the first H2 or H3 |
  | Bold-wrapped headings from the CMS and Docs exports | Stripped in `normalise` |
  | Blog close with no product link | Allowed when the outline's Conclusion Plan says no product fits |

- **Replay of runs 18-21:** 44 blocks became 40. The four removed are exactly the miscalibrated kinds.
- **Live-site finding:** the published WHS article links `/au/sds-management-articles/how-to-build-a-risk-register/`, which returns 404 (one of the not-live slugs).

### Phase 3 (done): one profile per content type

- **`types.yaml` holds each content type's check profile (`checks:`) and its prompt structure.** The structure pieces are heading case, keyword rule, H1 options, outline order, intro plan, FAQ plan, headings-only form, draft structure and meta-title rule; a type without one uses the blog's.
  - `prompting.type_structure` fills the outline and draft prompts from the structure pieces.
  - `prompting.check_profile` serves `sop.profile_of`, which `check_article` and `check_outline` read instead of `content_type == "outbound"` conditions.
  - A prompt can no longer ask for what a check forbids. A test renders every prompt for every content type with no placeholder left unfilled.
- **Guest posts (outbound profile):**
  - **Not required:** Key Takeaways, FAQ, References, a verb-first close, the "this article" sentence, or the keyword in the title or a heading (advisory instead).
  - **The title:** when it came from the brief sheet (the brief has a source reference), the H1 must be it word for word, ignoring case, in the outline and the draft.
  - **Blocks:**
    - an intro that announces the article ("In this article…");
    - any sdsmanager.com link that isn't one of the brief's anchors;
    - a link in the close (read from the last real body section, not References);
    - anchors in adjacent sections, counted at H2 and H3 level;
    - a first anchor after the first 30% of the body text (both approved guest posts with anchors keep it).
  - **Rubrics:** a new `outline:outbound` rubric. The edit-step rubric for guest posts now includes the outbound draft rules instead of only naming them.
  - **Reviewer input:** the reviewer now gets the host's site profile on the outline, draft and edit steps.
- **Localise:**
  - not checked against the source keyword;
  - target-region pages and index rows count as inputs, so a correct `/uk/` link isn't "invented";
  - the reviewer sees the edited text localise worked from;
  - its own guard: acronyms, regulation references and citation numbers may change and the region slug in URLs is mapped, but a changed figure needs a new `[VERIFY]`.
- **Prompt contradictions removed:**
  - the blog's "never in two adjacent sections" (Fixture A);
  - every H2 must open with a bridge (the skill: about half open cold);
  - "no rhetorical questions" (now: questions you don't answer at once);
  - Title Case for every type (now the type's case);
  - the literal `++underlined text++` the replay found copied into a heading.
- **Replay of runs 18-21:** identical counts to phase 2.

### Phase 4 (done): mechanical fixes before any model round

- **FAQ answers may carry links** (the owner's rule, over the skill's "no hyperlinks in FAQ answers"). The check, both FAQ prompt lines in `types.yaml`, the draft rubric and Fixture B no longer forbid them. The blog draft and edit rubrics also lost the retired "no anchors in adjacent sections" line.
- **`sop.normalise` now also does these, on article steps:**
  - names the component headings: FAQ/FAQs/"(FAQ)" become Frequently Asked Questions, Sources/Bibliography/Works Cited become References, and a first-H2 "Key Points"/"TL;DR" becomes Key Takeaways;
  - fences an FAQ that has `###` questions but no `:::faq`;
  - turns H2/H3 topic-and-qualifier commas into colons, with the same test as the check (`_comma_for_colon`). H1s are left to the check, so a guest post's verbatim title is never touched.
- **`house.mechanical_fix`** (also run by Final cleanup):
  - canonicalises sdsmanager.com links: https, no `www.`, a trailing slash on a page path, query and fragment kept;
  - removes a copied `++underlined text++` placeholder.
- **The URL-sourcing check** compares canonical forms and reports each page once, however it is spelled.
- **Smaller fixes:** heading checks ignore `{#anchor}` tags, and `## Metadata Options:`, `## SEO Metadata` and `## Metadata` are split off as metadata.
- **Fixture B** gains a `fixes:` list (repairs the mechanics must make). Its comma defect now sits in the H1, where the check still applies.
- **Replay of runs 18-21:** 40 blocks became 22. Comma headings went from 24 to 6, the six left being H1s; the rest of the drop is auto-fixed. Every remaining block is a defect read as real in phase 1.

### Phase 5 (done): what the reviewer and the reviser are given

- **Two lists.** The reviewer gets the blocking checks ("verified by script; they count against a PASS") separately from the advisories ("prompts to read: often false, they never count against a PASS by themselves; make one a finding only if it breaks a rubric rule on reading").
- **Measurements.** On article steps the reviewer also gets the article's FKGL against the target, whether sentence lengths look flat, the words against the guide, and the sections more than a grade above target (`sop.measurements`). It is told to judge the grade only from these.
- **Data-backed inputs.**
  - Article steps get the internal index and the product pages the rubric judges links against.
  - Plans get a longer excerpt of the search results (3,500 words, from 2,000).
  - The edit rubric's lines that needed the full draft are rewritten: protected spans, negations and markers are enforced by the guard and no longer re-checked from memory, and the grade is judged from the measurements.
- **Findings carry an example rewrite and a level.** Each reviewer finding gives an example rewrite where the fix is wording (the content-editing skill's "skin in the game"), and the reviser is told to use it. The reviewer may tag a finding `[strategic]` (the intent is wrong, or the piece duplicates a published article with no distinct angle) or `[structural]` (a section missing, out of scope or out of order, a promise not paid off). Strategic holds for a person with no revision; structural on an article joins the send-back, and on a plan it is revised in place.
- **Concrete values for the reviser.**
  - A close with no product link names the outline's planned product URL (`outline_plan` reads it from the Conclusion Plan).
  - An unsourced citation lists the subsections the inputs do give for that standard.
  - The reviser now gets the brief's notes, and on a guest post the site profile.
- **Verdict parsing** accepts bold or colon headings ("**Findings:**"), drops "None." items, and treats a reply with no headings as findings.
- **Hold notes** lead with "Look at first:", the open findings grouped into at most three themes ("2× invented URL"), before the full list.

Phases 1 and 2 matter most: phase 1 makes misfires measurable offline, and phase 2 removes the largest class by construction.

## Decisions for the owner

1. **Fixture A:** one or two recently approved sdsmanager.com articles (blog), and one approved guest post, as the zero-false-failure reference.
2. **Adjacent-section anchors on blogs:** a house rule, or guest posts only (the blog skill has no such rule)?
3. **Reading-grade floor:** accept the skill's "a grade or two above target where precise terms require it" as a computed floor per section?
4. **Comma-for-colon in headings** (added today, not in the skill): keep it narrowed to plain topic-qualifier headings, or drop it?
5. **Public history:** the planned slugs were committed earlier today. Leave the history as is, or rewrite it?
6. **The corrupted passage** in `ehs-outbound-blog/references/voice-and-style.md`: repair it in the skill (it is the source the rubrics copy from).
