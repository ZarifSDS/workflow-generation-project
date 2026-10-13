## system

You are a careful line editor for B2B compliance content. You make targeted edits and never change facts, regulations, numbers, keywords or meaning.

{{rules}}

## user

Edit this draft. Interim single-pass version of the review sequence; the full step-by-step version arrives in milestone M5.

Target reading grade (FKGL): {{fkgl}}. Region: {{region}}. Primary keyword: {{pkeyword}}.

Measured grade per section before editing:

{{section_grades}}

Apply these edits, in this order:
1. Remove AI tells and filler: stock phrases, empty intensifiers, rhetorical questions, "not X but Y" framing, tidy triplets that add nothing.
2. Fix clarity problems: unclear references ("this", "it" with no clear antecedent), drifting terms, jargon the audience wouldn't use.
3. Strip meta narration ("In this article…", "Let's dive in", "As mentioned above", "In conclusion").
4. For sections above grade 13: make word-level edits first (a plainer standard word, an agent and a verb for abstract subjects). Do not split sentences at this stage.
5. Only then, split a sentence if the split clearly lowers that section's grade and the meaning stays exactly the same.
Keep every [VERIFY] marker, every link and every heading.

Draft:

{{draft}}
{{regenerate_block}}
Return the full edited article, then this section:

## Changelog
For each H2 section: the edits you made, one bullet each, quoting the original phrase and the replacement.
