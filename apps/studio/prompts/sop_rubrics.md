# SOP rubrics, one section per pipeline step (read by apps/studio/sop.py; docs/sop.md explains them)

## site_crawl

- The profile describes the dominant pattern across the pages read, not one page: narrative mode, voice and person, heading case and shape, paragraph length, typical length, reading-level range, links, spelling.
- Narrative mode is `personal` only where the articles carry first-person stories; otherwise `informational`.
- The recommendations say how the guest post should look on this site (heading case, nesting, lists, tables, closing pattern) and what to avoid.
- The profile governs surface only; it does not set the article's depth. Nothing in it tells the writer to match thin host content.

## research

- Search intent is classified and its consequence for depth stated (basic query: cover everything; precise query: basics briskly, depth on the precision point).
- What Ranks reports the title framing, the shared H2 topics, the formats and the one unique thing a page does, from the search results given. Without search results it says so.
- Must Include lists what every ranking page covers; Missing Opportunity lists what they miss, get wrong or explain badly. Nothing is padded.
- Regulation Depth is light by default: it names the specific parts of the regulation the supporting queries and the ranking pages call for, and says what to leave out. It never plans a tour of the statute.
- The Keyword Table holds the primary and secondary keywords, the autocomplete and related terms worth targeting, the regional term where it differs, each with intent and a planned placement.
- Anchor Opportunities names internal pages (published articles, product pages) and external primary sources, with anchor text and a target section, using only URLs that appear in the inputs.
- Questions Searchers Ask are real searcher questions, marked body or FAQ.
- Sources are tiered and each has a use; URLs only from the inputs.
- Every claim carries its source and a status; everything not "primary read" carries [VERIFY]; enumerated lists carry their item count.
- Cannibalization names the overlapping sdsmanager.com article (or "no overlap") and the route, and says which subtopics it already covers in depth.
- Questions for the Requester lists what would change the article, each with an assumed answer, or "None."
- No invented regulations, figures or URLs anywhere.

## outline

- The chosen format matches what ranks and the length is calibrated to the ranking median, stated as a guide.
- Every H1 option is phrased as the searcher's query, carries the primary keyword, and is reader-friendly; the recommended one is marked.
- The first body H2 after Key Takeaways answers the primary query; every H2 is a real search query or the plain name of what the searcher wants; no H2 reuses the H1's question.
- Every H3 passes the necessity test (two or more distinct sub-questions under its H2, a reader would scan for it, it can't be a paragraph).
- The questions the H1 asks are answered in the first 30% of the plan by order, never by cutting.
- Every Must Include item has a section; every Missing Opportunity has a home; every fact has one home section (no planned repeats across steps, FAQ and conclusion).
- Depth per section follows the research's Regulation Depth and Cannibalization: subtopics a published article already covers in depth are short here and link to it.
- The Keyword and Anchor Map places every keyword and anchor from the research in a section; no two adjacent sections carry an sdsmanager.com anchor.
- The Intro Plan names the opener (a generic example or the pain point), why the knowledge matters, the snippet answer and the "this article" scope promise.
- The Conclusion Plan names the delivery gap, one action for this week, and the one product page that closes the gap (never an article or a lead magnet), or says why none fits.
- The FAQ Plan has three to seven questions, People Also Ask first, none answered by the body.
- The Claim Verification Table lists every planned claim with source and status.
- Structure Decisions log every order, split, merge and depth call with the alternative considered.
- The Headings-Only Outline is plain `H1:`/`H2:`/`H3:` lines, no prose: `H2: Key Takeaways` second, the verb-first CTA heading before the FAQ, and `H2: Frequently Asked Questions` last with each question as an `H3:`.

## draft

- Intro, in order: a generic example or the pain point the reader recognises; the topic and why knowing it matters to this reader; one or two snippet sentences answering the primary query with the primary keyword in the first 100 words; a bridge after any number; last, a scope sentence with the literal words "this article" naming the core contents. Four to seven sentences, no "Imagine", no "In today's workplace".
- Key Takeaways: three to seven standalone facts in article order, the first answering the primary query; no bullet leans on another (no "that", "this", "the same" pointing outside itself) and none uses coverage framing.
- The first H2 carries the core answer. Every question heading opens with its direct, self-contained answer. Every H3 passes the necessity test.
- The article answers the supporting search queries completely and in the ranking pages' depth; regulation is cited only where it settles a question (the research's Regulation Depth), never as a tour.
- Facts and figures carry [SRC: url] with URLs from the inputs only; uncertain claims carry [VERIFY]; nothing is invented; enumerated lists match the source's count; no deflection sentences ("check the current figure for your state").
- Second person by default; plain, specific, standard words (no "simpler" synonyms that lose meaning, no metaphors, no meta narration beyond the scope sentence); no promotional voice; no author credentials.
- Citation capsules where the outline marked them: one self-contained passage with a claim, a data point and its named source.
- Internal links: the anchors the outline mapped, natural noun-phrase anchors, no two sdsmanager.com anchors in adjacent sections, no link-only sentences, at least three sdsmanager.com links for a blog article or a flagged shortfall. Guest posts: each product anchor is the plain solution to a pain point just raised, in a section on the same topic as the page.
- Conclusion under a verb-first CTA heading naming the reader's task and outcome: the delivery gap, one action for this week, then the one product page (never an article or a lead magnet), linked in its sentence and described only by what the page supports; a button label on its own line when the brief's CTA style is button. Never "Conclusion".
- FAQ: three to seven questions in a `:::faq` block, each answer mirroring the question's subject in its first sentence (no bare Yes/No), two or three sentences, no links, varied landings.
- References listed with URLs; house mechanics (no dashes, straight quotes, Title Case headings, no emoji, no horizontal rules).
- Metadata options: three each for Meta Title (40-60 characters, keyword near the front, not a question, unlike the H1), Meta Description (150-160 characters, complete sentences, keyword), Slug, Tags (4-6), Excerpt (30-55 words, not the meta description).

## review_edit

- Everything in the draft rubric still holds after editing: intro order and scope sentence, Key Takeaways standalone test, answer-first headings, FAQ mirroring, CTA conclusion, anchors not adjacent.
- Protected spans survived: every figure, unit, date, regulation and section number, agency name, URL, quoted string and marker is unchanged from the draft; no negation was dropped.
- Machine-prose signatures are gone: no copula avoidance ("serves as"), significance inflation, tricolons, negative parallelism, participle tails, hedge stacks, stamped frames; no uniform sentence lengths.
- Clarity: every "this"/"that"/"it" has a named antecedent; one name per concept; no person or register breaks; jargon glossed for the stated reader; no metaphors standing in for plain words.
- Reading grade near the brief's target by syntactic unpacking only; legal vocabulary may keep a section a grade or two above; standard words kept over "simpler" ones.
- No fact is re-explained in a second section; the title's questions are still answered in the first 30%.

## localise

- Regulators, statutes, agencies, units, currency, spelling and examples all belong to the target region; none of the source region's remain.
- Every fact that changed region carries [VERIFY] unless the source for the target region was in the inputs.
- Structure, headings, Key Takeaways, FAQ and conclusion rules from the draft rubric still hold; the product link points at the target region's page.
