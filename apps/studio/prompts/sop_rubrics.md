# SOP rubrics, one section per pipeline step (read by apps/studio/sop.py; docs/sop.md explains them)

Each `## step` section is the rubric the SOP reviewer judges that step by. A `## step:content_type` section
is appended for that content type (`outbound` = guest post). The rules are vendored from the user's skills:
ehs-seo-blog-optimized (SKILL.md, step-1-research, step-2-draft, step-3-edit, component-specs, voice,
reader-flow, formatting, ai-patterns, linking, localization) and ehs-outbound-blog (SKILL.md,
voice-and-style). Where a rubric and a skill disagree, the skill is right and the rubric is the bug.

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
- Sources are tiered and each has a use; URLs only from the inputs. Edition years and figures are not stated from memory: where the current edition or value isn't confirmed by an input, the claim carries [VERIFY].
- Every claim carries its source and a status; everything not "primary read" carries [VERIFY]; enumerated lists carry their item count.
- Cannibalization names the overlapping sdsmanager.com article (or "no overlap") and the route, and says which subtopics it already covers in depth.
- Questions for the Requester lists what would change the article, each with an assumed answer, or "None."
- No invented regulations, figures or URLs anywhere.

## outline

- The chosen format matches what ranks and the length is calibrated to the ranking median, stated as a guide.
- Every H1 option is phrased as the searcher's query, carries the primary keyword, and is reader-friendly; the recommended one is marked.
- The first body H2 after Key Takeaways answers the primary query; every H2 is a real search query or the plain name of what the searcher wants; no H2 reuses the H1's question. An H2 with little direct search demand is folded into a parallel section.
- Every H3 earns its place: it stands alone without its parent heading, could carry the keyword or a close variant, and is plausibly a query someone would type. Question form where it expresses a real reader subquery; declarative or imperative where the H3 set mirrors a list stated above it (never converted to questions). Sub-questions nest under their parent, never as sibling H2s.
- The questions the H1 asks are answered in the first 30% of the plan by order, never by cutting.
- Every Must Include item has a section; every Missing Opportunity has a home; every fact has one home section (placement ledger: no planned repeats across steps, FAQ and conclusion).
- Depth per section follows the research's Regulation Depth and Cannibalization: subtopics a published article already covers in depth are short here and link to it.
- Order follows the reader's knowledge: definition, parts, purpose, activities, responsibility, regulation, system, measurement, practice; a distinction is drawn after the reader has seen the things distinguished, and every dependency is explicit.
- Keywords are never forced: the primary keyword sits in the H1, one H2 and the first 100 words, and in two or three headings only where a heading reads naturally with it; a heading bent to hold the keyword, or a keyword stuffed into a section, is the defect, and a shortfall is flagged, never fixed by force. Each secondary keyword is planned once where it fits or flagged.
- The Keyword and Anchor Map places every keyword and anchor from the research in a section; no two adjacent sections carry an sdsmanager.com anchor; an internal link is planned only where a section raises the problem the page solves, never in a defining or background section.
- The Intro Plan names the opener (a generic example or the pain point), why the knowledge matters, the snippet answer and the "this article" scope promise.
- The Conclusion Plan names the delivery gap, one action for this week, and the one product page that closes the gap (never an article or a lead magnet), or says why none fits.
- The FAQ Plan has three to seven questions, People Also Ask first, none answered by the body.
- The example plan: one early orientation example for a broad "what is" topic, then examples only for a difficult distinction, an overlap or an end-to-end process; no setting reused across sections unless as a deliberate running thread.
- Flow note per H2: what the previous section established, how this one advances it, and whether the seam needs an opening hinge, a closing bridge, implicit continuation or a clean stop.
- The Claim Verification Table lists every planned claim with source and status.
- Structure Decisions log every order, split, merge and depth call with the alternative considered.
- The Headings-Only Outline is plain `H1:`/`H2:`/`H3:` lines, no prose: `H2: Key Takeaways` second, the verb-first CTA heading before the FAQ, and `H2: Frequently Asked Questions` last with each question as an `H3:`.
- Fixed components keep their fixed forms and are exempt from the search-query rule: `Key Takeaways` (always exactly that, second), the CTA heading (verb-first, not a query) and `Frequently Asked Questions` (always exactly that, last). `Intro` in the Detailed Outline is a label for the introduction, not a heading. Never ask for these to be reworded.

## draft

### Components

- Intro, in order: a generic example or the pain point the reader recognises; the topic and why knowing it matters to this reader; one or two snippet sentences answering the primary query with the primary keyword in the first 100 words; a bridge that interprets any number before moving on; last, a scope sentence with the literal words "this article" naming the core contents. Four to seven sentences as one argument, each advancing the explanation, none repeating the definition in other words; no "Imagine", no "In today's workplace". The first two or three sentences work alone as a hook.
- Key Takeaways: three to seven standalone facts in article order, the first answering the primary query; no bullet leans on another (no "that", "this", "the same" pointing outside itself), none uses coverage framing, and the three front-loaded answers (snippet, first bullet, first H2 opener) share a fact from different angles, never the same sentence.
- The first H2 carries the core answer and advances beyond the intro (deepens the definition, sets scope, or draws the first distinction) instead of repeating it. `## Key Takeaways` (first H2), the verb-first CTA heading and `## Frequently Asked Questions` (last) are fixed components, never reworded into queries.
- Every question heading opens with its direct, self-contained answer in the first one or two sentences (about 40-60 words under an H2); a declarative heading names a complete subject whose opener stands without the parent; an opener serves its heading's promise (a "what to look for" heading opens with the thing to look for).
- Citation capsules where the outline marked them: one self-contained passage of about 120-180 words with a claim, a data point and its named source with year, in natural prose.
- Conclusion under a verb-first CTA heading naming the reader's task and outcome: the delivery gap, one action for this week, then the one product page (never an article or a lead magnet), linked in its sentence's own subject and described only by what the page supports; a button label on its own line when the brief's CTA style is button. Never "Conclusion", "Final Thoughts" or a section-by-section recap; the heading pushes toward the product without naming it.
- FAQ: three to seven questions in a `:::faq` block, each answer mirroring the question's subject in its first sentence (no bare Yes/No; where a straight "no" is the finding, open on the corrected fact), two or three sentences, no links, no body answer duplicated, varied landings across the set.
- Keywords read as a person writing about the topic would write them: the primary keyword in the H1, at least one H2, the first 100 words and two or three headings only where it reads naturally; a density of 1-2% is a stuffing ceiling, not a target; each secondary keyword once where it fits; long-tail and related keywords where they fit, never by quota. A keyword forced into a heading or a sentence that only exists to hold it is a defect; a placement that can't be made naturally is flagged for the editor, never forced, so never ask for a keyword to be added where it wouldn't read naturally.
- Acronyms: spelled out once in the body after the intro ("field level risk assessment (FLRA)"), then the acronym; not re-expanded in every section. Key Takeaways exempt; headings keep the ranking keyword form.
- References listed with URLs; metadata options (Meta Title, Meta Description, Slug, Tags, Excerpt) are stored separately by the studio and are not part of the text you see: never report them missing or ask for a metadata block.

### Flow and reasoning (reader-flow)

- Sentences follow from each other: for every pair, the reason B follows A is clear (explains, qualifies, supports, contrasts, exemplifies). Unrelated facts are not joined with "and"; where a sentence holds a stronger and a weaker idea it ends on the stronger.
- Each paragraph has one controlling point; a sentence that starts a different point belongs in a new paragraph with the connection built. Paragraphs could not be shuffled without loss.
- Each H2 opens from what the section before established: an opening hinge (a short clause before the answer, never a paragraph delaying it) where the relationship isn't obvious from the heading, a closing bridge that names the shared idea, implicit continuation, or a clean stop. Roughly half of sections open cold on the answer; a bridge is topic logic ("labels only work if workers can interpret them"), never a stock transition ("Additionally", "Now let's look at"). A moral that restates the section is cut; a hinge that points forward stays.
- No single frame ("Since X...", "Where X..., Y...", "[Subject] is...") opens or closes three or more sections in a row; the first sentences of the H2s, read in sequence, don't form one skeleton.
- Every assertion is complete in its own sentence: no "Those consequences are connected" or "Interpretation still matters" that postpones its meaning to the next sentence; abstract subjects are named with the practical distinction in the same sentence.
- Concepts come before shortened references to them (no "the department", "this system", "that duty" before the text established which); a relationship is explained before its parts are contrasted; a misconception is corrected after showing why a reader would connect the concepts, never with a cold "X is not Y".
- Examples: plot-free illustrative scenarios in accessible settings, each introduced through the concept it clarifies and why it fits before the object appears ("Chemical hazards can create all three risk types. A solvent drum..."); never a narrated anecdote (a specific person, day and outcome) in data-led content; no setting reused across sections; no example in an extraction zone before the answer; examples only where they reduce confusion, not in every H3.
- Lists: one or two sentences name the category or organising principle before bullets, without reciting them; no fact repeated across heading, intro sentence and first bullet; prose after a list only to interpret, except or connect, never to summarise every bullet.
- Each point has one home: a later section may apply a fact, never re-explain it (steps, examples, FAQ and the conclusion are where repeats creep in).
- A statistic beside the article promise is interpreted before the scope sentence; "By the end..." never follows an unexplained number.

### Voice

- Second person ("you") by default, also for law and compliance; third person only inside passages that must stand alone as quotable fact (a table cell, a statutory definition). About one reader-facing moment every 150-200 words, clustered at section closes and in the FAQ, as a diagnostic. Flatness is diagnosed by counting "you" before touching rhythm.
- No author persona, credentials, role or experience in the body.
- Active voice by default; weak agentless passives ("mistakes were made") are converted; the genuine regulatory passive whose actor is obvious stays ("safety data sheets must be retained for 30 years").
- Plain is/has: never "serves as", "stands as", "marks", "represents", "acts as", "functions as", and never "features", "offers", "boasts" for plain possession.
- Human syntax stays: plain verbs (use, try, move), simple constructions ("there is a"), mild hedges ("tends to", "usually"), factual definitives. Nothing is "elevated" into utilize, attempt, relocate.
- One name per concept; no cycling "the regulation" into "the framework" into "the mandate". Unfamiliar terms (including software terms and acronyms) are glossed inline on first use; domain-standard safety terms the audience owns are not glossed; a term is glossed once per chunk type and never re-glossed inside the same section.
- Sentence length varies by ear: no uniform mid-length cadence, no per-sentence cap; a short sentence after a long run lands the point. Contractions by ear, no target.
- Mechanical precondition openers ("With X in place, do Y", "Having done X, you can now Y") are recast to lead with the action.
- A question anywhere is answered before its own paragraph ends; a chain of questions answered in turn is fine; a pivot question left hanging is not.
- Structural turn markers ("Here's the thing, though:", "The takeaway?") are allowed where they replace a bold mini-header and are rotated; knowing asides that rate the fact ("the common trap", "one point often missed", "Here's why this matters", "the pattern is clear") are banned.
- Engagement without fluff: the clearest useful fact first; concrete stakes ("a missing Section 8 means a worker does not know a respirator is required") instead of asserted importance; real figures, deadlines and named rules where they answer the reader's question, never a number forced into a definitional section; a one-beat setup only when its payoff is the very next sentence; at least one useful thing the ranking pages miss. Not every section ends on a tidy wrap-up.

### AI patterns (replace the gesture with the concrete fact)

- No "From X, to Y" or "Whether X or Y" range scaffolds: state the rule and let one concrete endpoint carry the breadth.
- No reflexive rule of three (three adjectives, bullets or parallel phrases, or the same three-beat grouping across sections); a list a statute enumerates keeps the source's count.
- Negation framing: "It's not X, it's Y" is unfolded into the positive claim only where the affirmative carries the same meaning in fewer words; a "no" fact stays a "no" fact.
- No "-ing" padding or superficial "-ing" analysis ("...ensuring compliance", "...highlighting the importance", "...fostering a safety culture"): cut the clause or make it a specific, sourced sentence.
- No puffery ("plays a vital role", "a testament to", "underscores the importance of", "in the evolving regulatory landscape"); no vague attribution ("experts argue", "studies suggest", "many organizations find"): name the source and year or cut the claim.
- No challenges/outlook formula, no "X rather than Y" where Y adds nothing, no prophetic narrator ("And that changes everything"), no fake naming ("The X Framework"), no "nobody talks about this", no hedging filler ("It's worth noting", "Generally speaking").
- No meta-narration ("in this section", "as mentioned earlier", "let's dive into", "we'll unpack this below") and no generic preview sentence ("That gap carries a real cost", "This matters more now than ever"); the one allowed self-reference is the intro's "this article" scope sentence.
- "Not only X, but also Y" and rhetorical "While X, Y" at most once per article; formulaic transitions ("Additionally", "Furthermore", "Moreover", "Notably", "Consequently") replaced by a bridge that names the shared idea, or nothing.
- No personified abstractions ("a substance that quietly joins the list", "REACH shows up"), no enforcement drama or invented characters ("before an inspector does"), no vague idiom ("moving target", "left to drift"), no colloquial location or duty verbs for documents, data and duties (lives, sits, runs, bites, houses, holds: "that duty appears in Part 3.1", "records are kept"), no assembly or spatial metaphors ("stitch the records together", "the module houses your records").
- Dangling modifiers recast to name their subject; ambiguous shorthand ("SDS chemicals") written in full; no clause restated near-verbatim between an intro paragraph and the bullets under it.
- Repetitive sentence openers (three or more in a row with the same structure) varied; "statement: list" not repeated as a pattern.
- Plain diction wherever it loses no precision ("rarely" over "seldom", "countries" over "jurisdictions", "review" over "scrutiny"); genuine domain terms kept exactly (hierarchy of controls, near-miss, product stewardship); business clichés ("table stakes", "move the needle", "low-hanging fruit", "deep dive") replaced by the plain equivalent; legal and register metaphors ("a duty attaches to", "the standard contemplates") recast as actor-verb-object.
- "Key" at most twice as an adjective; the emphasizers "actually", "exactly", "really", "truly", "genuinely", "literally" about two uses each at most, cut wherever the sentence loses nothing; a banned intensifier is cut, not routed to one substitute.
- Affirmative, action-first directives in procedural prose, with cautions folded in; a standalone "do not" only where the prohibition itself is the information.
- Plain language never thins content: a sentence that trades a real capability, number or limitation for breezier prose has failed.

### Formatting and house style

- Title Case for every heading (house style, not a tell); zero em and en dashes anywhere (ranges as "10-15" or "10 to 15"); straight quotes only; no thematic breaks; no emoji.
- Bold sparingly: about one bolded phrase per 150 words, only for a defined term on first use, a threshold or a warning; never every occurrence, never mechanically across parallel sentences, never source or brand names. Bold-label lists ("Label: text") only where a list has genuine labels, never stamped across every list; other bullets are plain sentences or short noun phrases with varied length and grammar. Benefit tails ("so [outcome]") on at most a third of a list's bullets, never as a trailing "-ing" clause.
- Paragraphs run to 3-4 lines, fewer where the idea is done sooner; split where the controlling idea changes, never mid-idea; uniform paragraph size is noted, not blocking.
- The format follows the information: prose for reasoning, bullets for parallel items, numbers for sequence, a table for comparison or fields; no forced alternation. A table only where structured data would take three or more sentences as prose and the relationships matter (not for two columns and under four rows, not for sequences, not for one varying attribute); every table has a bold caption above it, is introduced in the preceding paragraph, and stays within five columns.
- Enumerate what the source enumerates (a statute's numbered list stays a list with the same count); follow the regulator's structure and cite the statute's sections, but only for the parts the research's Regulation Depth calls for.
- Give the sourced fact instead of a deflection ("check the current figure for your state" is not content); where a number genuinely varies, give the constant structure, a sourced representative range with its date, or the most current figure, with a check-with-the-regulator note only as a trailing qualifier.
- Named sources with years in the prose ("OSHA's 2024 HazCom update requires..."), not only in References; one canonical name per regulation, agency and standard; an abbreviation defined once and used consistently.
- Figures and figures-with-dates carry `[SRC: url]` right after the claim, pointing at the exact page (a document and section where the research gave no URL is acceptable); unconfirmed regulatory specifics (threshold, citation, frequency, retention period, edition year) carry [VERIFY]; a figure that re-indexes on a schedule is labelled "as at [date]"; nothing is invented and no edition year is stated from memory.
- `[VISUAL: type, description]` lines only where a visual reduces effort (data chart from cited statistics, process diagram, illustration of an abstract concept, photo of a real scene, comparison), rarely more than one per 1,500 words and not in every section.

### Links

- Every sdsmanager.com or wagtail link comes from the inputs (internal index, product registry, brief anchors, search results, research, outline); an unseen URL is a fabrication however plausible, and is removed or replaced by an unlinked mention or [VERIFY], never by another guessed URL.
- The anchor is a noun phrase already in the sentence (write the sentence as if no link existed, then link the phrase that names the concept, requirement or tool); it never describes its destination ("[guide covers X]", "[X] explains"), is never "click here", "learn more" or a raw URL, and the sentence reads grammatically with the link removed. Product and category names are mass nouns with no article ("audit and inspection software", never "an audit and inspection software").
- An internal link solves a problem the section has just raised; a section that defines a term cannot host a product link; no sentence exists only to carry a link ("For more on this, see our guide").
- At most one internal sdsmanager.com link per H2 section, no two sdsmanager.com anchors in adjacent sections, never two hyperlinks in one sentence, never two consecutive hyperlinks in one paragraph, none inside FAQ answers; external authority links sit at the claim they support (government, standards bodies, peer-reviewed; up to about four in a standard article, scaling to about one per item in a roundup), never in a trailing list.
- At least three sdsmanager.com links for a blog article (the conclusion's product link counts) or a flagged shortfall, never a forced one; at most one feature-level product link per major section, placed where the reader feels the problem, with the deepest relevant registry page winning (module page over landing page, never both for the same purpose); the platform is "EHS Solution by SDS Manager", distinct from the SDS Manager chemical product. No competitor products, no login or paywalled pages.
- The brand passes the forced-mention test: replace it with the solution category; if the sentence reads as well, the brand name goes. No "At SDS Manager, we...", no promotional final sentence, no "which is where X helps".

## draft:outbound

These rules govern a guest post on a third-party site and override the blog rules above where they conflict (the outbound skill is the source):

- SITE_PROFILE governs the surface: heading case (sentence case by default, title case only where the host uses it), heading length and nesting (H3s only where the host uses them; otherwise numbered H2s, lists or bold-lead paragraphs), paragraph shape (line breaks every two or three visual lines on a phone), list types, tables (none unless the host publishes them), closing pattern (a closing heading only if the site shows one), register. Depth and completeness come from the SERP, not the host, and the piece is written well above the host's baseline.
- Formats rotate across H2s as the outline assigned them (prose, bullets, numbered steps, bold-label definitions, bold-lead paragraphs), with no two consecutive H2s sharing a dominant format; at most one "Label: description" bullet list in the article; long runs of plain paragraphs are broken up with a list or bold-lead run.
- Heading form follows the query surface (question or how-to shaped where the ranking pages and People Also Ask phrase it that way, declarative where it names the subject as clearly); every heading stands alone when lifted (the disambiguating noun is in the heading); at most one H2 carries the country or region name; a brief-supplied title keeps its wording.
- Body sections do not answer their heading back: no opener mirroring the heading ("Under 'What is a COSHH assessment?', 'A COSHH assessment is...' is the FAQ tell"), no one-line answer capsules, no direct-answer body section; a reader landing mid-article knows what the section is about by its second sentence. Every paragraph opens on a complete sentence with a subject and a finite verb (no "Because...", "Only above five employees.", bare noun phrases). FAQ answers, only where the host asks for an FAQ, mirror by design as in the blog rules.
- Informational mode: no first-person sentence, personal experience, "have you ever" question, scene-setting narrator or "this article covers" line; voice second person or neutral as SITE_PROFILE shows; each section carries one quotable sourced passage (claim, number and named source with year in one sentence) placed in the body, not as the opener; the close is forward-facing with a concrete action in the host's closing style, no "I hope this helps", "Feel free to reach out", "Follow for more".
- The intro uses the three beats: a generic example or the pain point in third person; the topic and why knowing it matters with the keyword snippet in the first 100 words; the core content stated as content ("Inspectors check four things, in this order: ..."), never as a table of contents.
- Backlinks: each anchor from the brief exactly once, with the given text (a partial match where the exact text won't sit grammatically), mid-sentence inside the clause that describes the fix, in the section on the same topic as the page, where the article has just made the problem concrete; the first anchor in the first 30%, no two anchors in adjacent sections (H3s count), none in the close, no product name beside the anchor, no selling adjectives, no "this is where X helps", no call to action; only what the product page states. Two or three official-source links (regulator, legislation, public guidance) on natural noun-phrase anchors mid-sentence. No other sdsmanager.com links, and no promotion anywhere.
- The piece targets the brief's region for regulators, spelling and examples, and names the country only where it tells the reader which law or regulator applies.

## review_edit

- Everything in the draft rubric still holds after editing: intro order and scope sentence, Key Takeaways standalone test, answer-first openers, FAQ mirroring, CTA conclusion, anchors not adjacent, reader flow, voice, AI patterns, formatting and links.
- Protected spans survived: every figure, unit, date, regulation and section number, agency name, URL, quoted string and marker is unchanged from the draft ("1.5 metres" is not tidied into "1.5m"); no negation was dropped (re-read every sentence with no, not, never, none, cannot). A link the deterministic checks flagged as invented is removed on purpose: its loss is not a dropped span, and it is never put back or replaced with another URL from memory. Fewer than three real sdsmanager.com links is a flagged shortfall for the editor, not a reason to add links.
- Machine-prose signatures are gone: copula dress-up, significance inflation, tricolons, negative parallelism, participle tails, hedge stacks, stamped frames, formulaic transitions, knowing asides, figurative duty and location verbs; a banned word is cut or the sentence recast, never swapped for an unflagged synonym; nothing was de-slopped uniformly into equal short sentences.
- Clarity: every this/that/it has a named antecedent; one name per concept; no person or register break inside a paragraph (narration and commands not mixed); the intro, decision-support sections and conclusion keep the body's register and the closing does not sell harder than the body; jargon glossed for the stated reader; no metaphor standing in for a plain word; no idiom collision; both sides of a comparison stated; no circular definition.
- Reading grade near the brief's target by syntactic unpacking only (an agent and a verb for abstract subjects, stacked clauses split, terms glossed in place, fragments rejoined where splitting made prose choppy); legal vocabulary may keep a section a grade or two above; standard words kept over "simpler" ones; a sentence shortened for the score still carries the limitation that made it worth saying ("PPE protects workers" is a worse claim than "PPE protects one person at a time and only when worn properly").
- Reader flow survived the edit: paragraph seams still connect through a shared idea and each H2 still opens from the section before; a de-slop pass that left stacked, disconnected sentences is a defect to name. No comma splices after the rhythm work.
- GEO extraction integrity after all rewriting: question H2s and H3s still open with a self-contained answer; capsules still hold claim, data point and named source in one passage; the snippet, Key Takeaways and FAQ answers parse out of context; sources are named with years in the prose; one canonical name per regulation, agency and standard; front-loading holds.
- No fact is re-explained in a second section; the title's questions are still answered in the first 30%; no setting reused across examples.
- Keyword placement was not forced by the edit: no keyword was added to a heading or sentence where it doesn't read naturally, density stays under the 1-2% ceiling, and a placement shortfall is reported, never fixed by stuffing.
- Markers: every sourced statistic still carries its [SRC:] marker and every [VERIFY] still stands until a person resolves it; none was silently removed.

## review_edit:outbound

- The guest-post rules in the draft rubric for outbound still hold after editing: SITE_PROFILE surface (case, nesting, lists, no tables where the host has none, closing style), format rotation, no heading mirrored back by its opener, complete-sentence paragraph openers, NARRATIVE_MODE held throughout (no first person in informational mode; the framing sections drafted last are where the register drops), anchors unchanged in text and position, no promotion.
- Any regulatory specific an edit introduced carries [VERIFY]; a date within about three months of drafting carries [VERIFY at publication].

## localise

- Regulators, statutes, agencies, standards, statistics, compliance dates, retention periods, units, currency, spelling and examples all belong to the target region; none of the source region's remain, and no US regulator link is carried into a non-US variant.
- Every fact that changed region carries [VERIFY] unless the source for the target region was in the inputs; no regional jargon without a plain-language gloss.
- The heading hierarchy, bold, italics, lists, information structure, length and messaging are preserved; a snippet-worthy first sentence still answers the topic; FAQs keep the originals where they match local intent.
- The variant reads as a distinct piece: every sentence is rephrased with the same point and the same facts (no run of eight or more words shared with the base), clause order and openers vary, regional vocabulary is used (practise, organisation, "hazardous substances" where the regulator says it) without synonym cycling inside the variant; one name per concept still holds and canonical regulation, agency and standard names are protected spans.
- Nothing references the localisation process, the source country or "mirroring"; no meta-commentary about the adaptation.
- SDS Manager links use the region slug; a base link with no regional equivalent is replaced by the closest regional page or removed; the product link points at the target region's page; meta and tags change only where they name regulations or bodies that differ. A non-English variant keeps the body in English unless the brief asks otherwise, and translates the meta description (within 160 characters) and tags.
- Structure, headings, Key Takeaways, FAQ and conclusion rules from the draft rubric still hold.
