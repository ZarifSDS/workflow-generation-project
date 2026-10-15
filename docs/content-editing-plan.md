# Plan: mechanisms from the content-editing skill, and a more accurate reading grade (2026-10-15)

A plan only: nothing here is built yet. The owner decides which phases go ahead.

The source is the owner's `content-editing` skill (Ryan Law's *How to Edit*: strategic, then structural "30%", then line "90%" edits; `D:\ai-memory-vault\skills - zipped\sds-manager\SKILL.md`). `docs/sop-audit.md` mapped it onto the pipeline; this plan lists what is still missing and how to add it so that it helps whichever model writes. The rule throughout: **prefer a code check over a prompt instruction**, because a check gives the same answer for every model and a prompt only asks.

## Already in place (no change)

- Findings carry a level (strategic, structural, line, mechanical) and the level routes them: hold for a person, send the draft back, revise, or fix by script (`sop.py`, audit phase 2). This is the skill's core rule: never polish sentences before strategy and structure are sound.
- Every reviewer finding gives an example rewrite (`sop_review.md`), and hold notes open with the 1-3 themes to look at first.
- Answer-first sections (the skill's BLUF) in the draft rubric.
- `[VERIFY]` for unconfirmed facts, blocking publishing (the skill's `[NEEDS: ...]`).
- A reverse outline of the draft against the approved outline (`sop.check_reverse_outline`), today only for missing and out-of-order sections.

## Owner's decisions on this plan (2026-10-15)

- **Question-form headings take priority over "high-concept" (benefit-led) headers.** Question form rests on things that can be measured: People Also Ask, the ranking pages' headings and real queries. "Benefit" has no metric, so it can't be checked and never overrides a measurable rule. Benefit-led headers are dropped from the plan. The existing exceptions stay because each has its own basis: the fixed components (Key Takeaways, FAQ, the verb-first CTA heading), and step or list H3s, which are named as steps because they must be parallel to each other (item 4), not because a step name is a benefit.
- **"Keyword near the front" is a soft rule**: in the title shortlist (item 13) it raises a candidate's rank, never removes one. The only hard title check stays the existing one (the primary keyword appears in the title).

## Phase 1: the structural edit (the "30% edit"), at the outline and the draft

| # | Mechanism | Step | How | Level and route |
|---|---|---|---|---|
| 1 | **Thesis**: one arguable claim for the article and one line per H2 saying what the section establishes | Outline | A "Thesis" field in the outline prompt; a check that it is present; the reviewer judges whether the sections support it | Structural |
| 2 | **Keep every promise** ("Chekhov's gun"): "7 steps" has 7 steps, a promised example or checklist appears, a named region is covered | Outline, then draft | A check: promise words and counts in the H1 options, intro plan and H2s matched against the sections | Structural; at the draft, send back |
| 3 | **No overlap, nothing out of scope** (MECE): two H2s on the same thing, or a "why X matters" section in a how-to | Outline | A check: word overlap between headings; why-type headings when the research's search intent is how-to | Structural |
| 4 | **Parallel step and list headings**: sibling H3s in one grammatical form (all verbs, all "-ing", all questions) | Outline | A check on each heading's first word, for H3 sets under a step or list H2 only; H2s keep the question form | Line (cheap to fix at the outline) |
| 5 | **Weight follows importance** | Draft | Extend the reverse outline: each section's planned words (the outline already estimates them) against its written words; flag a section more than 50% off, or an answer H2 shorter than the median section | Structural |
| 6 | **"How, not why"**: about 80% how in a how-to | Draft | A check: the share of words under why or background headings when the intent is how-to | Structural |

## Phase 2: order and strategy

- **7. "Zoom in"** (pick the most valuable sub-topic instead of an ultimate guide) as a strategic hold, only when the research's Cannibalization section shows a published article already covering the broad topic. A person decides; a model never revises it. Otherwise the depth of the ranking pages wins.
- **8. Never polish before structure, enforced**: Review and edit doesn't run its line passes (deslop, clarity, grade tuning) while a structural finding from items 2, 5 or 6 is open; it sends the draft back first. This also saves model rounds.

## Phase 3: line-edit scans (the code finds, the model fixes)

- **9. Weasel words** ("improve results", "ensure compliance", "best practices", "experts believe"), only phrases the deslop scan doesn't already catch. Each hit asks the "five whys": replace it with the concrete mechanism from the research, or mark `[VERIFY]`.
- **10. Unbacked judgement and condescension** ("obviously", "of course", "common sense", "patently", "failed to"): "according to whom?", then cite or cut. This fits the newcomer default: the reader should never feel stupid.
- **11. Dense words**: a fixed list of wordy phrases. The safe ones are fixed by script ("due to the fact that" becomes "because", "in order to" becomes "to" where nothing else changes); the rest become suggestions. Only where the denser word is also the standard one (owner's rule: standard, clearer words for newcomers; jargon always glossed).
- **12. Steelman** the strongest objection or the reasonable status quo, in the third person, only for "vs" and "best X" articles and opinion-mode guest posts. The trigger is a code rule; the reviewer judges the result. No first-person anecdotes (no persona).

## Phase 4: titles

- **13. "Write 20 titles"**: the metadata step drafts about 20 candidates from the article's words and angles, then a script shortlists 3 to 5: length (40-60 characters for meta titles), no dashes, a query-shaped H1, different wording from the H1, no near-duplicates. The primary keyword near the front raises a candidate's rank but never removes one. The long list stays available to the editor.

## Phase 5: process

- **14. Read the whole piece**: the reviewer's context is cut at 2,500 words per input. Size the cut to the model's context window (OpenRouter reports 1,050k tokens for Luna), and always pass the full draft to Review and edit.
- **15. Recurring themes across runs**: count findings by theme over all runs, so the team sees which lessons keep coming back and tunes prompts from evidence.

## The reading grade (FKGL): making it more accurate

**How it is computed today.** Section and article grades use the blog skill's own formula (`vendor/ehs_seo_blog/scripts/metrics.py`, through `review.grade`): syllables are counted as vowel groups with a silent-e rule, sentences are split at `.!?` followed by a space and a capital or digit, and words are runs of letters. Its weak points:

| Weak point | Effect |
|---|---|
| Syllables guessed from vowel groups, no dictionary | Errors on irregular words; acronyms are wrong ("SDS" counts 1 syllable or none, though it is read "S-D-S", 3) |
| Numbers aren't counted as words; a citation such as "1910.1200(c)(1)" leaves stray letters counted as one-syllable words | Words per sentence and syllables per word drift |
| A sentence break after any abbreviation followed by a capital ("U.S. OSHA", "No. 5") | Extra sentences, a grade that reads low |
| Any section of 30 words or more is graded | FKGL on 30-100 words is statistically noisy |
| Two implementations in the codebase (the skill's formula and the `textstat` library in `apps/ai/evaluation/metrics.py`) | Numbers can disagree between screens and reports |

FKGL is itself an estimate (a 1975 formula), so no counting makes it "true". The goal is accurate counting, one set of rules everywhere, and an honest margin.

**The plan, in order:**

1. **One function everywhere.** Section table, whole-article grade, SOP checks, tuning, the vocabulary floor and the evaluation metrics all use the same counting.
2. **A measured baseline first.** A gold set of about 40 passages from Fixture A and stored runs, with sentences and syllables counted by hand for 10 of them (they become test fixtures). Report the error before and after each change, per weak point above.
3. **Syllables from a pronouncing dictionary.** The CMU Pronouncing Dictionary (open licence) for known words, the current heuristic as the fallback, and a small house lexicon for EHS terms and acronyms with the way they are read: SDS 3, PPE 3, GHS 3, HSE 3, CLP 3, JSA 3, OSHA 2, WHMIS 2, COSHH 1, REACH 1, SWMS 1. Letter-by-letter acronyms count one syllable per letter (W counts 3).
4. **Clear rules for numbers and references.** A number is one word, with the syllables of its spoken form. Citations, regulation section numbers, URLs and parenthetical sources ("(OSHA, 2024)") are left out of the grade, because they are references, not prose; the sentence around them is still graded.
5. **Sentence splitting that knows abbreviations**: e.g., i.e., etc., vs., No., U.S., U.K., Reg., Fig., initials, decimals and section numbers never end a sentence. A tested rule-based splitter, or the current regex with a protected-abbreviation list.
6. **No grade on too little text.** Show a grade from 100 words; below that, pool a short H3 with its parent section, or show "too short to grade" instead of a number that triggers tuning.
7. **A cross-check that needs no syllables.** Compute the Coleman-Liau index (from letters and sentences) beside FKGL. Where the two disagree by more than two grades, the section is marked "grade uncertain" and isn't auto-tuned.
8. **Show the margin.** The grade with about ±0.5, plus words, sentences and the share of sentences over 25 words (the part tuning actually changes). Tuning still starts only beyond one grade over target, aiming at the vocabulary floor.
9. **Skill parity.** The blog skill computes the same grade for the owner outside the studio, so the counting fixes go into the skill's `metrics.py` as well. Otherwise the vendored copy is recorded as a fork in `MANIFEST.json`, so the drift test stays honest.

Expected effect: grades move by up to about a grade on sections with many acronyms, numbers or abbreviations, and fewer sections are queued for tuning on counting errors alone.

## How every change is proven

- New checks start as advisory.
- Fixture A (the owner's five approved articles) must stay at zero blocks.
- Fixture B gets one planted defect per new check (a broken promise, overlapping H2s, mixed-form step headings, weasel words, unbacked judgement, a why-heavy how-to, an over-weighted section).
- The replay of stored runs (`manage.py sop_replay`) must show each check firing only on real problems before it is promoted to blocking (the method of `docs/sop-audit.md`).
- For the reading grade: the gold-set error before and after, and the number of sections whose "over target" status changes on the stored runs.

## Effort and order

| Work | Rough effort | Value regardless of model |
|---|---|---|
| Phase 1 (structure checks) and item 8 (no polish before structure) | About 1.5 days | Highest |
| Reading-grade accuracy (steps 1-8; step 9 with the owner) | About 1 day | High: every tuning decision rests on it |
| Phases 3 and 4 (line scans, titles) | About 1 day | Medium |
| Phases 2 and 5 (zoom-in hold, context size, themes) | About 1 day | Medium |
