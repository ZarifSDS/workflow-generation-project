"""The SOP self-review: a model-agnostic reviewer that checks each step's output against the house
standard operating procedure (docs/sop.md) and loops until it passes or the rounds run out.

How it works for one step (apps.studio.tasks.execute_step calls `apply` when `step.self_review` is on):

1. Deterministic checks (`check`): what a script can prove about the output for that step, derived from
   the skills' acceptance criteria (sections present, keyword placement, Key Takeaways and FAQ shape, house
   mechanics, anchors not in adjacent sections, ...). Each finding is `block` (must be fixed before the step
   can pass) or `advise` (reported, never blocks).
2. The reviewer model reads the rubric for the step (prompts/sop_rubrics.md), the brief, the inputs the step
   worked from, the deterministic findings and the output, and returns `VERDICT: PASS` or `REVISE` with
   numbered findings. It never rewrites.
3. If anything blocks, the step's own model applies the findings as a targeted revision
   (prompts/sop_revise.md).
   The revision is used only if it keeps the headings, most of the words and, for article steps, every
   protected span and negation (`apps.quality.review.accept_rewrite`).
4. Repeat up to `settings.STUDIO_SOP_MAX_ROUNDS` revisions. A step that still doesn't pass holds for a
   person's review with the open findings in its notes, whatever its gate setting.

The whole loop is logged in the version's metrics under "sop" and shown on the run screen.
"""

import re
from dataclasses import dataclass, field

from django.conf import settings

from apps.ai.types import ProviderError
from apps.quality import house
from apps.quality import review as quality_review

from . import prompting, textclean

STEPS = ("site_crawl", "research", "outline", "draft", "review_edit", "localise")
ARTICLE_STEPS = ("draft", "review_edit", "localise")
PLAN_STEPS = ("research", "outline")
MAX_FINDINGS_PER_REVISION = 6  # more than this and models restructure instead of fixing

DASH = re.compile("[–—]")
CURLY = re.compile("[“”‘’]")
META_NARRATION = re.compile(
    r"(?i)\b(?:in this (?:section|guide|post|piece|chapter)|"
    r"this (?:section|guide|post|piece|chapter) (?:outlines|covers|explains|describes|walks|discusses|looks)|"
    r"as (?:mentioned|discussed|noted) (?:above|earlier|"
    r"before)|let'?s dive in|we(?:'ll| will) (?:unpack|explore|dive)|in the (?:next|following) section|"
    r"below,? we)\b"
)
LINK_CARRIER = re.compile(
    r"(?i)\b(?:"
    r"for (?:a deeper|a closer|more|further) (?:look|detail|details|information|reading|guidance)"
    r"(?: (?:at|on|into|about))?"
    r"|refer to (?:our|the)"
    r"|see (?:our|the) [^.\n]{0,60}?(?:guide|article|resource|post)"
    r"|learn more (?:about|in|from)"
    r"|read (?:our|the) [^.\n]{0,40}?(?:guide|article|post)"
    r"|check out (?:our|the)"
    # To the sentence's end: a period inside a URL or "e.g." (no space after it) doesn't end it.
    r")\b(?:[^.!?\n]|[.!?](?=\S))*[.!?]"
)
LINKED_URL = re.compile(r"(?:https?|wagtail)://[^\s)\]]+")
COVERAGE_FRAMING = re.compile(r"(?i)\b(?:covers|you(?:'ll| will) learn|this article|explains how)\b")
POINTER_START = re.compile(r"(?i)^(?:that|this|these|those|the same|it)\b")
GENERIC_CLOSE = {
    "conclusion",
    "final thoughts",
    "wrapping up",
    "summary",
    "in summary",
    "key points",
    "next steps",
    "closing thoughts",
    "the bottom line",
    "takeaway",
    "takeaways",
}
RESEARCH_SECTIONS = [
    "Search Intent",
    "What Ranks",
    "Must Include",
    "Missing Opportunity",
    "Keyword Table",
    "Regulation Depth",
    "Anchor Opportunities",
    "Questions Searchers Ask",
    "Sources",
    "Claims",
    "Common Misconceptions",
    "Cannibalization",
    "Questions for the Requester",
]
OUTLINE_SECTIONS = [
    "Search Intent",
    "H1 Options",
    "Detailed Outline",
    "Intro Plan",
    "Conclusion Plan",
    "FAQ Plan",
    "Claim Verification Table",
    "Keyword and Anchor Map",
    "Structure Decisions",
    "Headings-Only Outline",
]
INTERNAL_LINK = re.compile(r"\]\((?:https?://(?:www\.)?sdsmanager\.com[^)]*|wagtail://page[^)]*)\)")
ANY_LINK = re.compile(r"\]\([^)]+\)")


@dataclass
class Finding:
    severity: str  # "block" | "advise"
    text: str

    def __str__(self):
        return f"[{self.severity}] {self.text}"


@dataclass
class Round:
    number: int
    verdict: str = ""  # PASS | REVISE | (error)
    fixes: dict = field(default_factory=dict)  # house mechanics fixed before the checks ({fix: count})
    checks: list = field(default_factory=list)  # deterministic findings as strings
    findings: list = field(default_factory=list)  # reviewer findings (break a rubric rule)
    suggestions: list = field(default_factory=list)  # reviewer suggestions (never block)
    revision: str = ""  # "applied" | "not used (reason)" | ""


@dataclass
class SopResult:
    text: str
    passed: bool
    rounds: list = field(default_factory=list)
    reviewer: str = ""
    error: str = ""

    def open_findings(self):
        last = self.rounds[-1] if self.rounds else None
        if not last:
            return []
        return [c for c in last.checks if c.startswith("[block]")] + list(last.findings)

    def as_metrics(self):
        return {
            "passed": self.passed,
            "reviewer": self.reviewer,
            "error": self.error,
            "rounds": [
                {
                    "number": r.number,
                    "verdict": r.verdict,
                    "fixes": r.fixes,
                    "checks": r.checks,
                    "findings": r.findings,
                    "suggestions": r.suggestions,
                    "revision": r.revision,
                }
                for r in self.rounds
            ],
        }

    def note(self):
        lines = ["## SOP self-review", ""]
        if self.error:
            lines.append(f"The self-review could not finish: {self.error}")
        for r in self.rounds:
            fixed = ", ".join(f"{n} {name}" for name, n in r.fixes.items())
            lines.append(
                f"- Round {r.number}: {r.verdict or 'no verdict'}; {len(r.checks)} check finding(s), "
                f"{len(r.findings)} reviewer finding(s), {len(r.suggestions)} suggestion(s)"
                + (f"; auto-fixed {fixed}" if fixed else "")
                + (f"; revision {r.revision}" if r.revision else "")
            )
        if self.passed:
            lines.append("")
            lines.append("Passed the SOP; the step continued on its own." if self.rounds else "")
        else:
            lines += ["", "**Held for your review.** Open findings:", ""]
            lines += [f"- {f}" for f in self.open_findings()[:12]] or ["- (none recorded)"]
        return "\n".join(line for line in lines if line is not None).strip()


# ---- Deterministic checks ----


def _sections(text):
    """[(name, body)] of the H2 sections; name '' for the text before the first H2."""
    return [(quality_review.heading_name(h) if h else "", b) for h, b in quality_review.split_sections(text)]


def _norm(name):
    """Section names compared loosely: case, punctuation and spacing don't count ("Headings-only outline:"
    is "Headings-Only Outline")."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _section_body(text, name):
    for heading, body in _sections(text):
        if _norm(heading) == _norm(name):
            return body
    return None


def _mechanics(text):
    findings = []
    if n := len(DASH.findall(text)):
        findings.append(
            Finding("block", f"{n} em or en dash(es); house style uses a comma, colon or new sentence")
        )
    if n := len(CURLY.findall(text)):
        findings.append(Finding("block", f"{n} curly quote(s); use straight quotes"))
    if n := len(house.EMOJI.findall(text)):
        findings.append(Finding("block", f"{n} emoji"))
    if n := len(house.THEMATIC_BREAK.findall(text)):
        findings.append(Finding("block", f"{n} horizontal rule(s)"))
    return findings


def _missing_sections(text, required):
    present = {_norm(name) for name, _ in _sections(text)}
    return [name for name in required if _norm(name) not in present]


def _table_rows(body):
    rows = [line for line in (body or "").splitlines() if line.strip().startswith("|")]
    return [r for r in rows[2:] if r.replace("|", "").replace("-", "").strip()] if len(rows) > 2 else []


def _items(body):
    """List items in a section, or its table rows when the model used a table instead."""
    listed = [line for line in (body or "").splitlines() if re.match(r"^\s*(?:[-*]|\d+[.)])\s+\S", line)]
    rows = _table_rows(body)
    return rows if len(rows) > len(listed) else listed


def _words(text):
    return len(quality_review.prose(text).split())


def check_research(text, ctx):
    findings = _mechanics(text)
    if missing := _missing_sections(text, RESEARCH_SECTIONS):
        findings.append(Finding("block", "missing section(s): " + ", ".join(missing)))
    if len(_table_rows(_section_body(text, "Keyword Table"))) < 3:
        findings.append(Finding("block", "the Keyword Table has fewer than 3 keyword rows"))
    questions = _items(_section_body(text, "Questions Searchers Ask"))
    if not 6 <= len(questions) <= 14:
        findings.append(Finding("advise", f"{len(questions)} searcher question(s); the SOP asks for 8-12"))
    if len(_items(_section_body(text, "Claims"))) < 3:
        findings.append(Finding("block", "fewer than 3 claims listed with their source and status"))
    cannibal = (_section_body(text, "Cannibalization") or "").lower()
    verdict_given = re.search(r"\bno\b[^.\n]{0,40}\boverlap|\bnone\b|\(a\)|\(b\)|\(c\)|\broute\b", cannibal)
    if cannibal and not verdict_given:
        findings.append(
            Finding("advise", "the Cannibalization verdict names no route (a, b, c) and no 'no overlap'")
        )
    pk = (ctx.get("pkeyword") or "").lower()
    if pk and pk not in text.lower():
        findings.append(Finding("block", f"the primary keyword '{ctx['pkeyword']}' never appears"))
    return findings


ARTICLE_PATH = re.compile(r"/(?:sds-management-articles|blog|articles?|resources|lead-magnets?)/")
MAX_KEYWORD_HEADINGS = 3  # the skill: the keyword in "two or three headings", never forced
KEYWORD_FILLER = {"a", "an", "the", "of", "for", "in", "on", "and", "your", "my", "our"}


def _stem(word):
    return word[:-1] if len(word) > 3 and word.endswith("s") else word


def _keyword_words(pk):
    """The keyword's words, each set also with its multi-word runs as acronyms ("safety data sheet" -> "sds").
    Returns a list of word sets; a heading matching any of them carries the keyword."""
    words = [w for w in re.findall(r"[a-z0-9]+", pk.lower()) if w not in KEYWORD_FILLER]
    variants = [words]
    for size in range(len(words), 1, -1):
        for start in range(len(words) - size + 1):
            acronym = "".join(w[0] for w in words[start : start + size])
            variants.append(words[:start] + [acronym] + words[start + size :])
    return [{_stem(w) for w in variant} for variant in variants]


def carries_keyword(heading, pk, share=1.0):
    """Whether a heading carries the primary keyword: verbatim, or every word of it (or `share` of them) in
    any order, with acronyms and plurals ("How to Read an SDS Quickly" carries "how to read a safety data
    sheet"). Exact-match demands made models force the phrase into headings (run 20)."""
    heading, pk = (heading or "").lower(), (pk or "").lower().strip()
    if not pk or pk in heading:
        return bool(pk)
    words = {_stem(w) for w in re.findall(r"[a-z0-9]+", heading)}
    return any(variant and len(variant & words) >= share * len(variant) for variant in _keyword_words(pk))


def first_h2_answers(heading, pk):
    """The answer-first rule, checked loosely: for a "how to X" keyword the first body H2 names the action X;
    otherwise it carries at least half the keyword."""
    match = re.match(r"how to (\w+)", (pk or "").lower())
    if match:
        return _stem(match.group(1)) in {_stem(w) for w in re.findall(r"[a-z0-9]+", (heading or "").lower())}
    return carries_keyword(heading, pk, share=0.5)


def _headings_only(text):
    body = _section_body(text, "Headings-Only Outline") or ""
    lines = []
    for line in body.splitlines():
        # Tolerate a list bullet or bold around the level ("- H2: ...", "**H2:** ...").
        match = re.match(r"^\s*(?:[-*]\s+)?\**(H[1-4]):\**\s*(\S.*?)\s*$", line)
        if match:
            text = match.group(2).strip("*").strip()
            if text.lower().rstrip(":") in ("intro", "introduction"):
                continue  # the intro has no heading; models list it anyway, so it isn't held against them
            lines.append(f"{match.group(1)}: {text}")
    return lines


def check_outline(text, ctx):
    findings = _mechanics(text)
    if missing := _missing_sections(text, OUTLINE_SECTIONS):
        findings.append(Finding("block", "missing section(s): " + ", ".join(missing)))
    lines = _headings_only(text)
    pk = (ctx.get("pkeyword") or "").lower()
    if not lines:
        findings.append(Finding("block", "the Headings-Only Outline has no `H1:`/`H2:`/`H3:` lines"))
        return findings
    if not lines[0].startswith("H1:"):
        findings.append(Finding("block", "the Headings-Only Outline must start with the `H1:` line"))
    if len(lines) < 2 or lines[1].lower() != "h2: key takeaways":
        findings.append(Finding("block", "the second heading line must be `H2: Key Takeaways`"))
    h2s = [line for line in lines if line.startswith("H2:")]
    if not h2s or h2s[-1].lower() != "h2: frequently asked questions":
        findings.append(Finding("block", "the last H2 must be `H2: Frequently Asked Questions`"))
    else:
        faq_index = lines.index(h2s[-1])
        faq_h3 = [line for line in lines[faq_index + 1 :] if line.startswith("H3:")]
        if not 3 <= len(faq_h3) <= 7:
            findings.append(
                Finding("block", f"{len(faq_h3)} FAQ question(s) under the FAQ heading; the SOP asks for 3-7")
            )
        if len(h2s) >= 2:
            close = h2s[-2][3:].strip().lower()
            if close in GENERIC_CLOSE:
                findings.append(
                    Finding(
                        "block",
                        f"the conclusion heading '{h2s[-2][3:].strip()}' is generic; "
                        "use a verb-first CTA heading",
                    )
                )
    body_h2s = [
        line for line in h2s if line.lower() not in ("h2: key takeaways", "h2: frequently asked questions")
    ]
    if len(body_h2s) < 3:
        findings.append(
            Finding("block", f"only {len(body_h2s)} body H2(s); a competitive article needs at least 3")
        )
    if pk:
        h1_options = (_section_body(text, "H1 Options") or "").lower()
        if pk not in h1_options and pk not in lines[0].lower():
            findings.append(Finding("block", f"no H1 option carries the primary keyword '{ctx['pkeyword']}'"))
        if not any(carries_keyword(line[3:], pk) for line in lines[1:]):
            findings.append(
                Finding(
                    "advise",
                    "no H2 or H3 carries the primary keyword; fine if none reads naturally (never force)",
                )
            )
        if body_h2s and not first_h2_answers(body_h2s[0][3:], pk):
            findings.append(
                Finding(
                    "advise",
                    f"the first body H2 '{body_h2s[0][3:].strip()}' doesn't answer the primary query "
                    f"'{ctx['pkeyword']}' (answer-first rule); lead with the answer unless the ranking pages "
                    "show a reason not to",
                )
            )
    if re.search(r"(?m)^#{1,3}\s+\S", _section_body(text, "Headings-Only Outline") or ""):
        findings.append(
            Finding("block", "the Headings-Only Outline uses Markdown `#` headings; write `H2:`/`H3:` lines")
        )
    return findings


def _intro(text):
    """The text between the H1 and the first H2."""
    body = re.sub(r"(?m)^#\s+.*\n?", "", text, count=1)
    return body.split("\n## ", 1)[0]


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if len(s.split()) > 2]


def _faq(text):
    body = _section_body(text, "Frequently Asked Questions")
    if body is None:
        return None, []
    items = re.split(r"(?m)^###\s+", body)[1:]
    return body, items


def check_article(text, ctx, *, metadata=True):
    findings = _mechanics(text)
    shape = "advise" if ctx.get("content_type") == "outbound" else "block"  # host-dependent on a guest post
    pk = (ctx.get("pkeyword") or "").lower()
    h1s = re.findall(r"(?m)^#\s+(.+)$", text)
    if len(h1s) != 1:
        findings.append(Finding("block", f"{len(h1s)} H1 heading(s); the article needs exactly one"))
    elif pk and pk not in h1s[0].lower():
        findings.append(
            Finding("block", f"the H1 '{h1s[0]}' doesn't carry the primary keyword '{ctx['pkeyword']}'")
        )
    intro = _intro(text)
    first_100 = " ".join(quality_review.prose(intro).split()[:100]).lower()
    if pk and pk not in first_100:
        findings.append(Finding("block", "the primary keyword isn't in the first 100 words"))
    if not re.search(r"(?i)\bthis article\b|\bwalk you through\b", intro):
        findings.append(
            Finding("block", "the intro has no scope sentence with the literal words 'this article'")
        )
    if not 3 <= len(_sentences(quality_review.prose(intro))) <= 9:
        findings.append(
            Finding(
                "advise",
                f"the intro has {len(_sentences(quality_review.prose(intro)))} sentences; "
                "the SOP asks for 4-7",
            )
        )
    sections = _sections(text)
    names = [name for name, _ in sections[1:]]
    if not names or names[0].lower() != "key takeaways":
        findings.append(Finding(shape, "`## Key Takeaways` must be the first H2, right after the intro"))
    else:
        bullets = _items(sections[1][1])
        if not 3 <= len(bullets) <= 7:
            findings.append(Finding(shape, f"{len(bullets)} Key Takeaways bullet(s); the SOP asks for 3-7"))
        for bullet in bullets:
            item = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", bullet).strip("* ")
            if COVERAGE_FRAMING.search(item):
                findings.append(
                    Finding("block", f"Key Takeaways bullet uses coverage framing: '{item[:80]}'")
                )
            elif POINTER_START.match(item):
                findings.append(
                    Finding("block", f"Key Takeaways bullet leans on another bullet: '{item[:80]}'")
                )
    headings = re.findall(r"(?m)^#{2,3}\s+(.+)$", text)
    if pk and not any(carries_keyword(h, pk) for h in headings):
        findings.append(
            Finding("block", "no H2 or H3 carries the primary keyword, even as a natural variant")
        )
    for heading in [*h1s[:1], *headings]:
        # One comma and no list word: a topic and its qualifier ("Worked Example, Acetone SDS"), which the
        # house style separates with a colon. A comma in a heading only lists items.
        if heading.count(",") == 1 and not re.search(r"(?i)\b(?:and|or)\b|&", heading):
            findings.append(
                Finding(
                    "block",
                    f"the heading '{heading.strip()}' joins a topic and its qualifier with a comma; "
                    "use a colon (house style)",
                )
            )
    stuffed = [h for h in headings if carries_keyword(h, pk)] if pk else []
    if len(stuffed) > MAX_KEYWORD_HEADINGS:
        # Run 20: told to put the keyword in a heading, the model appended it to every H2.
        findings.append(
            Finding(
                "block",
                f"the primary keyword is in {len(stuffed)} headings; keep it in two or three where it reads "
                "naturally and restore the others to plain topic headings",
            )
        )
    body_names = [n for n in names if n.lower() not in ("key takeaways", "frequently asked questions")]
    if pk and body_names and not first_h2_answers(body_names[0], pk):
        findings.append(
            Finding(
                "advise",
                f"the first body H2 '{body_names[0]}' doesn't answer the primary query '{ctx['pkeyword']}' "
                "(answer-first rule)",
            )
        )
    faq_body, faq_items = _faq(text)
    if faq_body is None:
        findings.append(Finding(shape, "no `## Frequently Asked Questions` section"))
    else:
        if not 3 <= len(faq_items) <= 7:
            findings.append(Finding(shape, f"{len(faq_items)} FAQ question(s); the SOP asks for 3-7"))
        if ":::faq" not in faq_body:
            findings.append(
                Finding(
                    "advise", "the FAQ isn't wrapped in a `:::faq` block, so the page gets no FAQ component"
                )
            )
        for item in faq_items:
            question, _, answer = item.partition("\n")
            answer = answer.strip()
            if ANY_LINK.search(answer):
                findings.append(
                    Finding("block", f"the FAQ answer to '{question.strip()[:60]}' contains a link")
                )
            if re.match(r"(?i)^(?:yes|no)[,.!]", answer):
                findings.append(
                    Finding(
                        "block",
                        f"the FAQ answer to '{question.strip()[:60]}' opens with a bare Yes/No; "
                        "mirror the question's subject",
                    )
                )
    body_names = [
        n
        for n in names
        if n.lower() not in ("key takeaways", "frequently asked questions", "references", "metadata options")
    ]
    if body_names:
        close = body_names[-1].strip().lower()
        if close in GENERIC_CLOSE or close.startswith("conclusion"):
            findings.append(
                Finding(
                    "block",
                    f"the closing heading '{body_names[-1]}' is generic; the SOP wants a verb-first CTA "
                    "heading naming the reader's task and outcome",
                )
            )
    if ctx.get("content_type") == "seo_blog" and body_names:
        # The blog close is gap → action → one product page (run 20 closed on a "Start Free Trial" label
        # with no link at all). An article or lead magnet is never the CTA target.
        close_links = INTERNAL_LINK.findall(_section_body(text, body_names[-1]) or "")
        if not close_links:
            findings.append(
                Finding(
                    "block",
                    f"the closing section '{body_names[-1]}' links no product page; link the one product "
                    "page the conclusion plan names, in the sentence that offers it",
                )
            )
        elif all(ARTICLE_PATH.search(link) for link in close_links):
            findings.append(
                Finding("block", "the close links an article; the CTA links a product page, never an article")
            )
    if ctx.get("content_type") == "seo_blog":
        if _section_body(text, "References") is None:
            findings.append(Finding("advise", "no `## References` section"))
        if (n := len(INTERNAL_LINK.findall(text))) < 3:
            findings.append(
                Finding(
                    "advise",
                    f"{n} sdsmanager.com link(s); the SOP asks for at least three, or a flagged shortfall",
                )
            )
    linked = [i for i, (_, body) in enumerate(sections) if INTERNAL_LINK.search(body)]
    if any(b - a == 1 for a, b in zip(linked, linked[1:], strict=False)):
        findings.append(Finding("block", "sdsmanager.com anchors sit in two adjacent sections"))
    findings += check_sourced_urls(text, ctx)
    findings += check_citations(text, ctx)
    for anchor in ctx.get("anchors") or []:
        url = anchor.get("url", "")
        if url and (n := text.count(f"]({url}")) != 1:
            findings.append(
                Finding(
                    "block",
                    f"the anchor '{anchor.get('text', '')}' → {url} appears {n} time(s); "
                    "the brief wants it exactly once",
                )
            )
    if (
        ctx.get("content_type") == "outbound"
        and body_names
        and INTERNAL_LINK.search(sections[-1][1] if sections else "")
    ):
        last_body = _section_body(text, body_names[-1]) or ""
        if INTERNAL_LINK.search(last_body):
            findings.append(
                Finding("block", "a product anchor sits in the close; guest posts carry none there")
            )
    for match in LINK_CARRIER.finditer(text):
        findings.append(
            Finding(
                "block",
                "a sentence exists only to point at another page: '"
                + match.group(0).strip()[:90]
                + "'; cut it, and link a noun phrase in a sentence that states the fact or the fix instead",
            )
        )
        break
    for match in META_NARRATION.finditer(text):
        findings.append(Finding("block", f"meta narration: '{match.group(0)}'"))
        break
    words = _words(text)
    if pk and words:
        density = text.lower().count(pk) / words  # occurrences per word, the usual SEO-tool reading
        if density > 0.025:
            findings.append(
                Finding("block", f"primary keyword density {density:.1%}; keep it under about 2%")
            )
    target = ctx.get("wordcount")
    if target and words and not 0.6 * target <= words <= 1.7 * target:
        findings.append(Finding("advise", f"{words} words against a guide of {target}"))
    if metadata and (counts := ctx.get("metadata_counts")):
        short = [kind for kind, n in counts.items() if n < 3]
        if short:
            # A note for the log only: the options live outside the text, so no revision can act on it.
            findings.append(Finding("note", "fewer than three metadata options for: " + ", ".join(short)))
    return findings + check_skill_scripts(text)


MAX_FLOW_PROMPTS = 6  # the flow check's prompts go to the reviewer; more than a handful drowns the rubric


def check_skill_scripts(text):
    """The skill's own deterministic link and flow checks (vendored `link_check.py` and
    `editorial_flow_check.py`). Link placement the skill bans blocks; the flow check's output is, in its
    own words, review prompts and not rewrite instructions, so it advises."""
    from apps.quality import scripts

    findings = []
    try:
        links = scripts.run_json("links", text)
        flow = scripts.run_json("flow", text)
    except (scripts.ScriptError, OSError, ValueError) as error:
        return [Finding("note", f"the skill's link and flow checks didn't run: {error}")]
    banned = (
        ("two_links_one_sentence", "two links in one sentence"),
        ("consecutive_links", "two links back to back in one paragraph"),
        ("link_only_sentences", "a sentence that is little more than its link"),
    )
    for key, label in banned:
        for item in (links.get(key) or [])[:2]:
            findings.append(Finding("block", f"{label} (link_check): '{_one_line(item)}'"))
    for heading, count in links.get("sections_over_one_internal") or []:
        findings.append(
            Finding("block", f"'{heading}' has {count} sdsmanager.com links; one per section (link_check)")
        )
    prompts = []
    for item in flow.get("scope_sentence_directly_after_statistic") or []:
        prompts.append(f"the scope sentence follows a statistic: '{_one_line(item['scope_sentence'])}'")
    geo = flow.get("h3_geo") or {}
    for item in geo.get("opener_flags") or []:
        prompts.append(f"H3 '{item['heading']}': {item['reason']}")
    if geo.get("majority_flag"):
        prompts.append("broad 'what is' content: most genuine subquery H3s should be question-shaped")
    for item in flow.get("possible_unintroduced_definite_nouns") or []:
        prompts.append(f"'{item['noun']}' may not be introduced before: '{_one_line(item['sentence'])}'")
    for item in flow.get("incomplete_abstract_assertions") or []:
        prompts.append(f"an abstract assertion with no explanation: '{_one_line(item['sentence'])}'")
    for item in flow.get("contextless_example_openers") or []:
        prompts.append(f"an example opens before its concept: '{_one_line(item['sentence'])}'")
    for item in flow.get("possible_prose_list_duplication") or []:
        prompts.append(f"prose and list may repeat each other near line {item['line']}")
    findings += [Finding("advise", f"{p} (editorial_flow_check)") for p in prompts[:MAX_FLOW_PROMPTS]]
    return findings


def _one_line(text, limit=110):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def check_site_crawl(text, ctx):
    findings = _mechanics(text)
    if _section_body(text, "Site profile") is None:
        findings.append(Finding("block", "no `## Site profile` section"))
    elif len(_table_rows(_section_body(text, "Site profile"))) < 4:
        findings.append(Finding("block", "the Site profile table has fewer than 4 rows"))
    return findings


CHECKS = {
    "site_crawl": check_site_crawl,
    "research": check_research,
    "outline": check_outline,
    "draft": check_article,
    "review_edit": lambda text, ctx: check_article(text, ctx, metadata=False),
    "localise": lambda text, ctx: check_article(text, ctx, metadata=False),
}


def context_from(step):
    brief = step.run.brief
    counts = {}
    for kind in ("title", "meta", "slug", "tags", "excerpt"):
        counts[kind] = step.run.metadata_options.filter(kind=kind).count()
    return {
        "pkeyword": brief.pkeyword,
        "skeywords": list(brief.skeywords or []),
        "fkgl": float(brief.fkgl),
        "wordcount": brief.wordcount,
        "region": brief.region,
        "content_type": brief.content_type,
        "cta_style": brief.cta_style,
        "anchors": list(brief.anchors or []),
        "metadata_counts": counts if step.key == "draft" else {},
        "allowed_urls": allowed_urls(step),
        "allowed_citations": allowed_citations(step) if step.key in ARTICLE_STEPS else None,
    }


# A regulation reference down to its subsection: "1910.1200(g)(8)", "29 CFR 1910.1200 (b)", "§ 1904.7(a)".
CITATION = re.compile(r"(?<![\d.])(\d{3,4}\.\d{1,4})\s?((?:\([a-z0-9]{1,4}\))+)", re.I)


def _citation(match):
    return (match.group(1) + match.group(2)).lower()


def allowed_citations(step):
    """Subsection references the step's inputs carry. An article may cite those (or a parent of one) only;
    run 20 cited 1910.1200(c)(1), the definitions paragraph, for training, and nothing caught it."""
    return {_citation(m) for source in _input_sources(step) for m in CITATION.finditer(source or "")}


def check_citations(text, ctx):
    allowed = ctx.get("allowed_citations")
    if allowed is None:
        return []
    findings, seen = [], set()
    for line in text.splitlines():
        for sentence in re.split(r"(?<=[.!?])\s+(?=[A-Z\[*])", line):
            if MARKER_VERIFY.search(sentence):
                continue
            for match in CITATION.finditer(sentence):
                cite = _citation(match)
                if cite in seen or any(source.startswith(cite) for source in allowed):
                    continue
                seen.add(cite)
                findings.append(
                    Finding(
                        "block",
                        f"the regulation reference {match.group(0).strip()} isn't in the research or the "
                        "search results; cite only subsections the inputs give, or keep the claim and add "
                        "[VERIFY] after the sentence",
                    )
                )
    return findings


INVENTED_CITATION = re.compile(r"\[block\] the regulation reference (.+?) isn't in the research")
MARKER_VERIFY = re.compile(r"\[\s*VERIFY\s*(?::[^\]]*)?\]", re.I)


URL = re.compile(r"(?:https?|wagtail)://[^\s)\]\"'>]+")
INVENTED_URL = re.compile(r"\[block\] the link (\S+) isn't in the inputs")


def allowed_urls(step):
    """Every URL the step was given: the internal index and product registry, the brief's anchors, the search
    results and the approved research and outline. A URL in an article that isn't among them was invented
    (the skill's "URLs only from results" rule); `wagtail://…?id=` links come from the editor and are kept."""
    return {url.rstrip(".,;:") for source in _input_sources(step) for url in URL.findall(source or "")}


def _input_sources(step):
    """The texts a step worked from: the internal index, product registry, brief anchors and notes, the
    search results and the approved research and outline."""
    from . import houseref

    run, brief = step.run, step.run.brief
    return [
        houseref.related_articles_block(brief),
        houseref.product_pages_block(brief.region),
        " ".join(a.get("url", "") for a in (brief.anchors or [])),
        prompting.approved_output(run, "search_results"),
        prompting.approved_output(run, "research"),
        prompting.approved_output(run, "outline"),
        brief.notes or "",
    ]


def check_sourced_urls(text, ctx):
    """Block findings for sdsmanager.com and wagtail links that don't come from the inputs."""
    allowed = ctx.get("allowed_urls")
    if allowed is None:
        return []
    findings = []
    seen = set()
    for url in URL.findall(text):
        url = url.rstrip(".,;:")
        own = "sdsmanager.com" in url or url.startswith("wagtail://")
        if (
            not own
            or url in allowed
            or url in seen
            or re.match(r"wagtail://(?:page|document|image)\?id=\d+", url)
        ):
            continue
        seen.add(url)
        findings.append(
            Finding(
                "block",
                f"the link {url} isn't in the inputs (invented URL); use a URL from the index, "
                "the product pages or the research, or drop the link",
            )
        )
    for target in sorted(set(RELATIVE_LINK.findall(text))):
        findings.append(
            Finding(
                "block",
                f"the link target '{target}' is a bare path or a marker, not a page from the inputs "
                "(invented URL); use a full URL from the index or the product pages, or drop the link",
            )
        )
    return findings


# A Markdown link whose target is a site-relative path or a marker: never a page the inputs gave (run 20).
RELATIVE_LINK = re.compile(r"\]\((/[^)\s]*|\[[A-Z]+[^)]*\])\)")


def check(step_key, text, ctx):
    checker = CHECKS.get(step_key)
    return checker(text, ctx) if checker else []


# ---- The reviewer and the revision ----


def rubric(step_key, content_type=None):
    """The step's section of prompts/sop_rubrics.md, plus the `## step:content_type` section when the
    file has one (guest posts follow the outbound skill where it differs from the blog rules)."""
    text = prompting._template("sop_rubrics")

    def section(name):
        match = re.search(rf"(?ms)^## {re.escape(name)}\s*$\n(.*?)(?=^## \w|\Z)", text)
        return match.group(1).strip() if match else ""

    base = section(step_key)
    extra = section(f"{step_key}:{content_type}") if content_type else ""
    return f"{base}\n\n{extra}".strip() if extra else base


def parse_verdict(reply):
    """(verdict, findings, suggestions) from the reviewer's reply. Findings are the numbered items under
    "## Findings"; items under "## Suggestions" never block. A REVISE with no findings counts as PASS."""
    reply = reply or ""
    match = re.search(r"(?im)^\**\s*verdict\s*:?\**\s*:?\s*\**\s*(PASS|REVISE)", reply)
    verdict = match.group(1).upper() if match else ""
    findings, suggestions = [], []
    bucket = findings
    for line in reply.splitlines():
        if re.match(r"(?i)^\s*#{1,3}\s*suggestions?\b", line):
            bucket = suggestions
            continue
        if re.match(r"(?i)^\s*#{1,3}\s*findings?\b", line):
            bucket = findings
            continue
        item = re.sub(r"^\s*(?:\d+[.)]|[-*])\s+", "", line).strip()
        if item and item != line.strip() and not item.lower().startswith("verdict"):
            bucket.append(item[:400])
    if not verdict or (verdict == "REVISE" and not findings):
        verdict = "REVISE" if findings else "PASS"
    return verdict, findings[:12], suggestions[:8]


def _inputs_for(step):
    """What the step worked from, for the reviewer (truncated so the prompt stays within limits). The
    search results travel with the plans so the reviewer can tell a URL from the inputs from an invented
    one."""
    run = step.run
    parts = []
    if step.key in ("research", "outline"):
        parts.append(("Search results the step saw", prompting.approved_output(run, "search_results"), 2000))
        parts.append(("Published sdsmanager.com articles (internal index)", base_related(step), 600))
    if step.key in ("outline", "draft"):
        parts.append(("Approved research", prompting.approved_output(run, "research"), 2500))
    if step.key == "draft":
        parts.append(("Approved outline", prompting.approved_output(run, "outline"), 2500))
    if step.key in ("review_edit", "localise"):
        parts.append(("The approved draft it edited", prompting.approved_output(run, "draft"), 2500))
    blocks = []
    for label, text, limit in parts:
        if text:
            words = text.split()
            shown = " ".join(words[:limit]) + (" …(truncated)" if len(words) > limit else "")
            blocks.append(f"### {label}\n\n{shown}")
    return "\n\n".join(blocks) or "(this step has no earlier approved input)"


def base_related(step):
    from . import houseref

    return houseref.related_articles_block(step.run.brief)


def _guard(step_key, before, after, droppable=()):
    """Whether a revision may replace the text. An edited or localised article keeps every protected span
    (the skill's rule for rewriting approved prose). A draft is still being written, so its revision only has
    to keep the sections, most of the words, every link and every negation. `droppable` lists URLs the checks
    flagged as invented: a revision may remove those even where spans are protected."""
    for url in droppable:
        before = before.replace(url, "")
    if step_key in ("review_edit", "localise"):
        return quality_review.accept_rewrite(before, after)
    after = (after or "").strip()
    if not after:
        return False, "empty output"
    if len(after.split()) < 0.6 * len(before.split()):
        return False, "too much text was removed"
    if step_key == "draft":
        urls = set(re.findall(r"(?:https?|wagtail)://[^\s)\]]+", before))
        if lost_urls := sorted(urls - set(re.findall(r"(?:https?|wagtail)://[^\s)\]]+", after))):
            return False, "it dropped the link(s) " + ", ".join(lost_urls[:3])
        lost = len(quality_review.NEGATION.findall(before)) - len(quality_review.NEGATION.findall(after))
        unfolded = len(quality_review.UNFOLDABLE_NEGATION.findall(before)) - len(
            quality_review.UNFOLDABLE_NEGATION.findall(after)
        )
        if lost > max(unfolded, 0):
            return False, "it dropped a negation (no, not, never…), which can reverse a claim"
    names_before = [name for name, _ in _sections(before) if name]
    names_after = [name for name, _ in _sections(after) if name]
    kept = {_norm(name) for name in names_after}
    lost = [name for name in names_before if _norm(name) not in kept]
    if lost and step_key == "draft" and len(names_after) == len(names_before):
        # An article heading may be reworded in place (the keyword into an H2, a colon for a comma): the
        # checks ask for exactly that (run 20). Count and order stay; plan section names stay fixed.
        lost = []
    if lost:
        return False, "it dropped or renamed the section(s) " + ", ".join(f"'{n}'" for n in lost[:4])
    if len(re.findall(r"(?m)^#{1,3}\s+.+$", after)) < len(re.findall(r"(?m)^#{1,3}\s+.+$", before)):
        return False, "sections were dropped"
    return True, ""


FIXED_HEADINGS = (
    (re.compile(r"(?im)^(\s*(?:[-*]\s+)?\**H2:\**\s*).*\bkey takeaways\b.*$"), "H2: Key Takeaways"),
    (
        re.compile(r"(?im)^(\s*(?:[-*]\s+)?\**H2:\**\s*).*\bfrequently asked questions\b.*$"),
        "H2: Frequently Asked Questions",
    ),
    (re.compile(r"(?im)^##\s+(?!Key Takeaways\s*$).*\bkey takeaways\b.*$"), "## Key Takeaways"),
    (
        re.compile(r"(?im)^##\s+(?!Frequently Asked Questions\s*$).*\bfrequently asked questions\b.*$"),
        "## Frequently Asked Questions",
    ),
)


BOLD_LABEL_LINE = re.compile(r"(?m)^[ \t]*\*\*([^*\n]{3,80}?)\**:?\*\*[ \t]*:?[ \t]*$")


def normalise_plan_headings(text):
    """Plans sometimes come back with bold labels instead of headings ("**Search Intent**"). A line that is
    only a bold label becomes a `## ` heading, so the section checks, the reviewer and the exports read it.
    Lines that carry `H2:`/`H3:` plan markers are left to the headings-only parser. Returns (text, count)."""

    def heading(match):
        label = match.group(1).strip().rstrip(":")
        if re.match(r"(?i)^H[1-4]\s*:", label):
            return match.group(0)
        return f"## {label}"

    new_text, count = BOLD_LABEL_LINE.subn(heading, text)
    # subn counts the H-line matches we left alone; count only real changes.
    return new_text, sum(1 for a, b in zip(text.splitlines(), new_text.splitlines(), strict=False) if a != b)


def normalise_fixed_headings(text):
    """Fixed components keep their fixed names: a model (or a reviewer) that turns `Key Takeaways` into a
    search query is corrected mechanically. Returns (text, count)."""
    count = 0
    for pattern, replacement in FIXED_HEADINGS:
        text, n = pattern.subn(replacement, text)
        count += n
    return text, count


def _strip_fences(text):
    text = (text or "").strip()
    match = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", text, re.DOTALL)
    return match.group(1).strip() if match else text


def length_rule(step_key, text, ctx):
    """The length the reviser must keep. Revisions tended to trim (run 19 ended 250 words under the guide and
    two revisions per step were refused for removing too much), so the floor is stated, not left implied."""
    words = len((text or "").split())
    floor = int(words * 0.9)
    rule = (
        f"\nLength: the output is about {words} words. Keep at least {floor}: cut only what a finding names, "
        "and where a finding removes a sentence, keep the fact it carried."
    )
    target = ctx.get("wordcount")
    if step_key in ARTICLE_STEPS and target:
        if _words(text) < target:
            rule += f" The article is already under its guide of {target} words, so never shorten it."
        else:
            rule += f" The guide is {target} words."
    return rule + "\n"


def link_sources(step_key, base):
    """For an article, the only pages a revision may link. Run 20's reviser, asked for more internal links
    without this list, invented a new sdsmanager.com URL every round and put [VERIFY] where a link went."""
    if step_key not in ARTICLE_STEPS:
        return ""
    return (
        "\nLinks: link only to pages listed here (or already linked in the output), with their URLs exactly "
        "as given. If no listed page fits a finding that asks for a link, leave the text without one; never "
        "write a URL from memory and never put [VERIFY] inside a link.\n\n"
        f"Internal articles:\n{base.get('related_articles') or '(none)'}\n\n"
        f"Product pages:\n{base.get('product_pages') or '(none)'}\n"
    )


def run_loop(step, text, call, max_rounds=None):
    """The review-revise loop. `call(prompt_name, context, task)` returns (text, "provider/model")."""
    max_rounds = settings.STUDIO_SOP_MAX_ROUNDS if max_rounds is None else max_rounds
    ctx = context_from(step)
    base = prompting.context_for(step)
    result = SopResult(text=text, passed=False)
    inputs = _inputs_for(step)
    rejection = ""
    for number in range(1, max_rounds + 2):
        current = Round(number)
        result.rounds.append(current)
        # House mechanics a script fixes better than a model (dashes, curly quotes, emoji, rules, spacing).
        result.text, current.fixes = house.mechanical_fix(result.text)
        if step.key in PLAN_STEPS:
            result.text, promoted = normalise_plan_headings(result.text)
            if promoted:
                current.fixes["bold labels made headings"] = promoted
        result.text, fixed = normalise_fixed_headings(result.text)
        if fixed:
            current.fixes["fixed component headings"] = fixed
        if step.key in ARTICLE_STEPS:
            # "Tags: …" / "Excerpt: …" lines under the H1 would publish as intro text.
            result.text, stray = textclean.strip_metadata_lines(result.text)
            if stray:
                current.fixes["metadata lines taken out of the article"] = sum(map(len, stray.values()))
        checks = check(step.key, result.text, ctx)
        current.checks = [str(f) for f in checks]
        reply, reviewer = call(
            "sop_review",
            {
                **base,
                "step_label": step.label,
                "rubric": rubric(step.key, step.run.brief.content_type),
                "inputs": inputs,
                "checks": "\n".join(f"- {f}" for f in checks if f.severity != "note") or "- (none)",
                "output": result.text,
            },
            "sop_review",
        )
        result.reviewer = reviewer
        current.verdict, current.findings, current.suggestions = parse_verdict(reply)
        blocking = [str(f) for f in checks if f.severity == "block"]
        if current.verdict == "PASS" and not blocking:
            result.passed = True
            break
        if number > max_rounds:
            break
        # Blocking checks always go; a handful of reviewer findings keeps the revision targeted.
        to_fix = blocking + current.findings[:MAX_FINDINGS_PER_REVISION]
        revised, _ = call(
            "sop_revise",
            {
                **base,
                "step_label": step.label,
                "findings": "\n".join(f"{i}. {f}" for i, f in enumerate(to_fix, 1)),
                "length_rule": length_rule(step.key, result.text, ctx),
                "link_sources": link_sources(step.key, base),
                "previous_rejection": (
                    f"\nYour previous revision was not used because {rejection}. Keep every section and "
                    "heading of the output below, and change only what the findings name.\n"
                    if rejection
                    else ""
                ),
                "output": result.text,
            },
            None,
        )
        revised = _strip_fences(revised)
        invented = [m.group(1) for m in (INVENTED_URL.match(str(f)) for f in checks) if m]
        invented += [m.group(1) for m in (INVENTED_CITATION.match(str(f)) for f in checks) if m]
        # A pointer sentence is cut, never reworded, so its link may go with it (run 20 deadlocked here).
        carried = [url for m in LINK_CARRIER.finditer(result.text) for url in LINKED_URL.findall(m.group(0))]
        ok, reason = _guard(step.key, result.text, revised, droppable=invented + carried)
        if not ok:
            # The next round reviews the unchanged text and tells the model why its revision was refused.
            current.revision = f"not used ({reason})"
            if rejection:
                # Two refused revisions in a row: this model won't fix it; stop spending calls and hold.
                current.revision += "; stopped after two refused revisions"
                break
            rejection = reason
            continue
        current.revision, rejection = "applied", ""
        result.text = revised.strip() + "\n"
    return result


def apply(step, output):
    """Run the loop on a StepOutput (apps.studio.executors) and fold the result into it."""
    from . import executors

    def call(prompt_name, context, task):
        messages = prompting.render(prompt_name, context)
        max_tokens = 4000 if task else executors.MAX_TOKENS.get(step.key, 8000)
        result = executors._call_text(step, messages, max_tokens=max_tokens, task=task)
        return result.text, f"{result.provider}/{result.model}"

    try:
        sop = run_loop(step, output.content, call)
    except (ProviderError, executors.StepError) as error:
        sop = SopResult(text=output.content, passed=False, error=executors.friendly_error(error))
    output.content = sop.text
    output.hold = output.hold or not sop.passed
    output.extra_metrics = {**(output.extra_metrics or {}), "sop": sop.as_metrics()}
    output.note = f"{output.note}\n\n{sop.note()}".strip() if output.note else sop.note()
    return output
