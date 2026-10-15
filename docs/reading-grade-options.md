# Reading grade: which system to use (recommendation, 2026-10-15)

The owner asked for a more modern grade-level system, like the one the Hemingway app uses, before building the reading-grade part of `docs/content-editing-plan.md`. This note says what the tools actually use (from their own pages), measures the candidates on the owner's five approved articles (Fixture A), and recommends one option. **The owner chose option C (2026-10-15); it is built: see "Built" at the end.**

## What the tools use, from their own docs

| Tool | Grade or score | What it flags beyond the number | Source |
|---|---|---|---|
| Hemingway | **Automated Readability Index (ARI)**, 1967: characters per word and words per sentence, no syllables. Plus targets grade 9 by default (Accessible / Default / Technical) | Hard (yellow) and very hard (red) sentences *relative to the target grade*, no published cut-off; adverbs, passive voice and qualifiers (blue); words with "simpler exact synonyms" (purple) | [ARI article](https://hemingwayapp.com/articles/readability/automated-readability-index) ("This tool leverages ARI"), [Readability](https://hemingwayapp.com/help/docs/readability), [Highlighted issues](https://hemingwayapp.com/help/docs/highlighted-issues) |
| Yoast SEO | **No grade any more.** Flesch Reading Ease was taken out of the readability score in 19.3 (July 2022), kept only in Insights | Sentence length (over 20 words), word complexity (English: over 7 characters, not in the 5,000 most frequent words, not capitalised; warn above 10%), passive voice (max 10%), paragraph length, subheading distribution, transition words | [Flesch page](https://yoast.com/flesch-reading-ease-score/), [Word complexity](https://yoast.com/word-complexity-assessment), [Methodology](https://yoast.com/content-analysis-methodological-choices-explained/) |
| Grammarly | Flesch Reading Ease (0-100, aim for 60+) | Its own clarity suggestions | [Grammarly blog](https://www.grammarly.com/blog/readability-scores/) (no support-site article found) |
| Readable | Shows them all (FKGL, Fog, Coleman-Liau, SMOG, ARI, Dale-Chall, Spache, Lix …); its A-E rating combines them with an **unpublished** formula | Long sentences, wordy and complex words | [Algorithms](https://help.readable.com/en/article/what-readability-algorithms-do-you-use-1r016wq/), [Ratings](https://help.readable.com/en/article/what-are-readablepros-letter-grades-how-are-ratings-calculated-5ezjfm/) |

Two things follow:

- **No tool has a more modern formula.** Hemingway's ARI (1967) is older than FKGL (1975). Lexile is proprietary (MetaMetrics). Newer model-based measures (trained on corpora such as CLEAR) need a model, which the owner's "computable without a model" rule excludes for the grade itself.
- **What makes Hemingway and Yoast feel modern is the diagnosis, not the formula:** they point at the sentence or word to change and say why. Yoast dropped Flesch for exactly this reason: one number mixes sentence length and word length, so the writer "won't know which part needs fixing". The studio already does part of this (stacked sentences for the tuner, the vocabulary floor), but the editor only sees one number per section.

## Measured on Fixture A (the owner's five approved articles)

Scratch script over `tests/fixtures/sop/a*/` with the studio's prose stripping; textstat 0.7.13 for everything except `FKGL skill` (the vendored `metrics.py`). Sections of 100 words or more.

| Article | FKGL skill | FKGL textstat | ARI | Coleman-Liau | Dale-Chall | Sentences > 20 words |
|---|---|---|---|---|---|---|
| AU WHS risk management (blog) | 13.1 | 12.3 | 13.6 | 11.5 | 10.9 | 58% |
| US job safety analysis (blog) | 11.1 | 10.6 | 11.1 | 9.7 | 9.9 | 48% |
| UK risk registers (guest) | 10.4 | 10.1 | 12.1 | 9.8 | 10.1 | 50% |
| US HazCom training (guest) | 9.4 | 9.3 | 10.8 | 10.8 | 11.1 | 30% |
| US life sciences EHS gaps (guest) | 12.7 | 12.0 | 13.5 | 12.5 | 11.7 | 49% |

What the numbers say:

1. **ARI ranks the articles like FKGL but reads 0.5-2 grades higher on this content.** Switching to it would move every target in the briefs (they are FKGL targets, and so is the sheet's FKGL column and the skill) without making anything more accurate.
2. **Coleman-Liau is a poor cross-check here.** FKGL, ARI and Coleman-Liau differ by more than two grades on **16 of 29 sections** (median spread 2.1, max 5.6; for example "What Does 'Reasonably Practicable' Mean": FKGL 12.1, ARI 12.8, CLI 8.3). The plan's step 7 ("over two grades apart → grade uncertain, no auto-tuning") would switch tuning off on most sections. That step needs changing whichever option is chosen.
3. **Dale-Chall barely moves** (8.9-12.4 across very different sections): every EHS term counts as an unfamiliar word, so it measures the topic more than the writing.
4. **Counting errors are real.** "Make WHS Risk Reviews Part of a Routine": skill FKGL 15.7 vs textstat 12.9 on the same four sentences. The plan's counting fixes (steps 1-6) matter more than the choice of formula.
5. **Absolute Hemingway-style flags would light up the approved articles.** At a fixed sentence grade of 12+, 70 of the AU blog's 97 sentences are flagged, and Yoast's 20-word limit fails all five (30-58% of sentences over it, Yoast warns above 25%). Flags have to be relative to the brief's target and calibrated on Fixture A, as Hemingway's own docs describe ("far more complex than your target score").

## Options

| | What changes | For | Against |
|---|---|---|---|
| A. Replace FKGL with ARI (Hemingway's) | Every grade, target and tuning threshold | Matches Hemingway's number; no syllable counting | Grades jump 0.5-2; the briefs, the sheet and the skill all speak FKGL; no gain in accuracy on this content |
| B. Show ARI beside FKGL | A second number per section | Familiar to Hemingway users | Two numbers that disagree by 1-2 grades with no rule for which wins; more noise on the run screen (the UX audit just reduced it to one readout) |
| **C. Keep FKGL, fix the counting, add Hemingway/Yoast-style diagnosis (recommended)** | Plan steps 1-6 and 8 as written; step 7 changed; sentence and word flags added | One grade everyone already uses, counted correctly; the editor sees *which* sentences and words raise it, and why | More to build than A (about 1.5 days instead of 1) |

## Recommendation: option C

Keep FKGL as the one grade (it matches the briefs, the sheet and the skill), make its counting accurate (plan steps 1-6), and add what actually makes Hemingway and Yoast useful:

1. **Hard and very hard sentences, relative to the target.** Grade each sentence (same counting) and flag "hard" at target + 4 and "very hard" at target + 7 (starting values, to be calibrated so Fixture A shows only a few flags per section and Fixture B's planted long sentences are all caught). These become the tuner's input in place of today's longest-over-N-words list (`review.stacked_sentences`), so tuning works on the sentences a reader would stumble on, not just the long ones.
2. **Split the grade into its two drivers** (Yoast's reason for dropping Flesch): next to each section's grade, "sentence length: X words on average" and "word length: Y syllables a word, floor Z" (the vocabulary floor already computes this). The editor sees whether to split sentences or whether the terms set the grade, which is the owner's "standard clearer words win even if the grade rises" made visible.
3. **Complex words, with EHS terms exempt.** Yoast's rule (over 7 characters, outside the 5,000 most frequent words) plus exemptions for acronyms, the brief's keywords, glossed terms and a short EHS term list. Shown as a percentage and highlighted, never auto-replaced, and never a block (the owner's rule above).
4. **Passive voice share**, advisory (a simple "was/were/been/is/are + past participle" detector; Yoast's 10% as the first threshold, calibrated on Fixture A). Adverbs are already covered by deslop's intensifier scan; qualifiers by the hedging patterns in deslop. Neither needs a new scan.
5. **Change plan step 7.** Drop Coleman-Liau as the uncertainty signal (it disagrees on most sections). Mark a grade "uncertain" only when the section is short (under 100 words, already step 6) or when the counting fixes changed it by more than a grade.

No model is needed for any of this; all of it is deterministic and testable on Fixtures A and B with `manage.py sop_replay` before and after.

**If the owner prefers Hemingway's number on screen anyway,** option B can be added later as a hover detail without touching targets or tuning.

## Built (2026-10-15, option C)

`apps/quality/readability.py` is now the only reading-grade counting: section and article grades, tuning, the vocabulary floor, the SOP reviewer's measurements, the search-results and site-crawl page grades and the evaluation metrics all call it (textstat is no longer used in code). Tests: `tests/test_readability.py` (a hand-counted gold set, the flags, pooling, and a Fixture A calibration test).

**Counting (plan steps 1, 3-6):**
- Syllables: a house lexicon for EHS acronyms (SDS 3, OSHA 2, COSHH 1, …), then the CMU Pronouncing Dictionary (`data/syllables.tsv`, 19,669 words where it disagrees with the skill's heuristic, e.g. "safety" 2, not 3), then the heuristic. Other acronyms of up to three letters, or with no vowel, are read letter by letter.
- A number is one word, its spoken syllables **capped at two** (a change from the plan: counted in full, "146,700 claims in 2023 to 2024" made a grade-26 sentence on Fixture A, though a reader takes a figure in at a glance).
- Citations (`29 CFR 1910.1200(h)(3)`, `32(1)(b)`), URLs and parenthetical sources (`(OSHA, 2024)`) aren't counted; flagged sentences still show them as written.
- Sentences never end at e.g., i.e., U.S., Dr., an initial and similar; "No.", "Reg.", "Fig." only before a number, so an FAQ answer's "No." still ends a sentence.
- **No grade below 100 words.** A long H2's short H3s are pooled with the ones after them (the FAQ is graded in a few groups, marked "graded with the next n H3s"). A short H2 section shows "too short to grade" and isn't auto-tuned; its sentence flags still show.

**Diagnosis (advisory, never a block):**
- Hard sentences read 6 or more grades above the target on their own, very hard ones 10 or more (sentences of 12 words or more). On Fixture A at target 9 that is 1.7 hard and 0.3 very hard per graded section (45 sections); on the stored runs 1.0 and 0.5; the tests hold it under 2.5 and 1.0. The tuner now gets these sentences, hardest first (it used to get the longest ones).
- What sets the grade: words a sentence (and the share over 25) and syllables a word, with the floor the section's words allow.
- Complex words: Yoast's English rule (over 7 letters, not among wordfreq's 5,000 most frequent words, `data/frequent-words.txt`, CC BY-SA 4.0, not capitalised), with `data/ehs-terms.txt`, the brief's keywords and terms glossed in brackets exempt. Warn above 10%; Fixture A's articles run 0-8% by section.
- Passive voice: a be/get verb plus a past participle. Warn above 10% of sentences (Yoast). Fixture A runs about 13% by section, so on this content the warning is common and is shown in muted text, not as a hold.

**Plan step 7 changed** as recommended: no Coleman-Liau cross-check; a grade is withheld only when the text is too short.

**Effect on the stored runs** (14 article versions): the article grade moves by -0.5 to +0.9 (median +0.5). Graded sections fall from 170 to 56, and sections over target from 134 to 40, mostly because model drafts have many sections under 100 words (each now "too short to grade", the plan's step 6). The SOP's blocking checks don't use grades, so Fixture A still raises no blocks and Fixture B is still caught in full.

**Open:**
- Plan step 2's 40-passage gold set (this build has 12 hand-counted words, 8 numbers and the sentence and reference rules).
- Step 9 (skill parity) waits for the owner: the blog skill's own `metrics.py` still uses the old counting, so the owner sees a different FKGL outside the studio. The vendored copy is unchanged; the studio no longer calls its FKGL.
- textstat, nltk and the image's cmudict download are now only needed by `data/build_wordlists.py` and could leave the image.
- Short H2 sections with very hard sentences aren't auto-tuned.
