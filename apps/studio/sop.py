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

import copy
import difflib
import re
from collections import Counter
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
# Coverage framing describes the article ("This article covers…", "you'll learn"), not a source: "Section 8
# covers exposure controls" is a fact (docs/sop-audit.md, phase 6).
COVERAGE_FRAMING = re.compile(
    r"(?i)\b(?:(?:this|the) (?:article|guide|post|section) (?:covers|explains|walks)|you(?:'ll| will) learn"
    r"|in this article|we(?:'ll| will)? (?:cover|explain|look at))\b"
)
# A bullet that leans on another one; a dummy "It is…" / "It's…" stands alone.
POINTER_START = re.compile(r"(?i)^(?:that|this|these|those|the same|it(?!\s+is\b|'s\b))\b")
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


LEVELS = ("strategic", "structural", "line", "mechanical")


@dataclass
class Finding:
    """One deterministic finding.

    `level` decides the route (docs/sop-audit.md, after the content-editing skill's hierarchy: strategy,
    then structure, then lines): a strategic finding holds for a person; a structural one in an article is
    not given to the line reviser but sends the step back to be regenerated from its plan; a line finding
    is revised in place. `allows` is what its fix may change, and the guard allows exactly that:
    `drop_urls` (links it may remove), `rename` (headings it may reword; "*" for any), `drop_negations`
    (how many negations may go) and `drop_spans` (protected spans it may change). A fix that needs a
    change nothing allows is refused, so a check never asks for what the guard forbids."""

    severity: str  # "block" | "advise" | "note"
    text: str
    level: str = "line"
    allows: dict = field(default_factory=dict)

    def __str__(self):
        return f"[{self.severity}] {self.text}"


def permissions(findings):
    """The union of what a set of findings allows a revision to change."""
    merged = {"drop_urls": set(), "rename": set(), "drop_negations": 0, "drop_spans": set()}
    for finding in findings:
        allows = getattr(finding, "allows", None) or {}
        merged["drop_urls"] |= set(allows.get("drop_urls", ()))
        merged["rename"] |= set(allows.get("rename", ()))
        merged["drop_negations"] += int(allows.get("drop_negations", 0))
        merged["drop_spans"] |= set(allows.get("drop_spans", ()))
    return merged


def _links_in(text):
    return [url.rstrip(".,;:") for url in re.findall(r"(?:https?|wagtail)://[^\s)\]\"'>]+", text or "")]


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
    route: str = ""  # "" | "send_back" (structural findings remain) | "hold" (a strategic finding)
    routed: list = field(default_factory=list)  # the findings behind the route
    best_round: int | None = None  # set when a hold keeps an earlier round's text
    sent_back: bool = False  # the step was regenerated once with the structural findings as its note

    def blocks(self):
        last = self.rounds[-1] if self.rounds else None
        return [c for c in (last.checks if last else []) if c.startswith("[block]")]

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
            "route": self.route,
            "routed": self.routed,
            "best_round": self.best_round,
            "sent_back": self.sent_back,
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
        if self.sent_back:
            lines.append("- Structural findings sent the step back once: it was regenerated from its plan.")
        if self.best_round:
            lines.append(f"- Kept round {self.best_round}'s text: later rounds weren't better.")
        if self.passed:
            lines.append("")
            lines.append("Passed the SOP; the step continued on its own." if self.rounds else "")
        else:
            lines += ["", "**Held for your review.**"]
            if self.route == "hold":
                lines.append("A strategic finding needs a person before anything is revised:")
            elif self.route == "send_back":
                lines.append(
                    "Structural findings remain (a missing or misplaced section): fix them in the plan or "
                    "send the step back, rather than editing sentences."
                )
            if themes := self.themes():
                # The content-editing skill's overview: the few things to look at, before the full list.
                lines += ["", "Look at first: " + "; ".join(themes) + "."]
            lines += ["", "Open findings:", ""]
            lines += [f"- {f}" for f in self.open_findings()[:12]] or ["- (none recorded)"]
        return "\n".join(line for line in lines if line is not None).strip()

    def themes(self, limit=3):
        """The open findings grouped by kind, most frequent first, as short labels ("2× invented URL")."""
        counts = Counter(_theme(f) for f in self.open_findings())
        return [f"{n}× {kind}" if n > 1 else kind for kind, n in counts.most_common(limit)]


THEMES = (
    ("invented URL", r"isn't in the inputs \(invented URL\)|is a bare path or a marker"),
    ("meta narration", r"meta narration"),
    ("unsourced regulation reference", "the regulation reference"),
    ("pointer sentence", "exists only to point|little more than its link"),
    ("product link in the close", "links no product page|the close links an article|sits in the close"),
    ("heading wording", "joins a topic and its qualifier|tacked onto|is generic|carries the primary keyword"),
    (
        "missing or misplaced section",
        "Key Takeaways` must|Frequently Asked Questions` section|missing section",
    ),
    ("FAQ answer", "the FAQ answer"),
    ("intro", "scope sentence|announces the article|first 100 words"),
    ("links", "anchor|sdsmanager.com link|two links|back to back"),
    ("house mechanics", "dash|curly quote|emoji|horizontal rule"),
)


def _theme(finding):
    text = str(finding)
    if text.lower().startswith(("[strategic]", "[structural]")):
        return text[1 : text.index("]")] + " (reviewer)"
    for label, pattern in THEMES:
        if re.search(pattern, text, re.I):
            return label
    return "the reviewer's findings" if not text.startswith("[") else check_kind(text)[:40]


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


def _canon(name):
    """A section name reduced for near-miss matching: "&" is "and", British -isation/-ise spellings are US,
    and a trailing "(…)" or ":" doesn't count."""
    name = re.sub(r"\s*\([^)]*\)\s*$|:\s*$", "", (name or "").strip())
    name = name.replace("&", " and ").lower()
    name = re.sub(r"isation\b", "ization", re.sub(r"ise\b", "ize", name))
    return _norm(name)


def canonical_section_names(text, required):
    """Rename `##` headings that nearly match a required section ("Keyword & Anchor Map", "Cannibalisation")
    to the required name, so a revision never has to rename one (the guard refuses renamed plan sections).
    Returns (text, count)."""
    wanted = {_canon(name): name for name in required}
    count = 0

    def fix(match):
        nonlocal count
        name = match.group(1).strip()
        if _norm(name) in {_norm(r) for r in required}:
            return match.group(0)
        key = _canon(name)
        target = wanted.get(key) or next(
            (wanted[k] for k in wanted if difflib.SequenceMatcher(None, key, k).ratio() >= 0.88), None
        )
        if not target:
            return match.group(0)
        count += 1
        return f"## {target}"

    return re.sub(r"(?m)^##\s+(.+?)\s*$", fix, text), count


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
    findings += _dropped_keywords_back(text, "Keyword Table", ctx)
    return findings


def _dropped_keywords_back(text, section, ctx):
    """The keyword filter (keyword_data.py) dropped these for a reason; a plan must not bring them back."""
    dropped = ctx.get("dropped_keywords") or {}
    first_cells = {
        re.sub(r"[*`\"“”]", "", row.strip().strip("|").split("|")[0]).strip().lower().replace("’", "'")
        for row in _table_rows(_section_body(text, section))
    }
    back = sorted(k for k in dropped if k in first_cells)
    if not back:
        return []
    reasons = "; ".join(f"'{k}' ({dropped[k]})" for k in back[:5])
    return [Finding("advise", f"the {section} uses keyword(s) the keyword data dropped: {reasons}")]


ARTICLE_PATH = re.compile(r"/(?:sds-management-articles|blog|articles?|resources|lead-magnets?)/")
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


QUESTION_WORDS = set(
    "does do is are can should must will would could has have need you your what how why when where who "
    "which there any it be get to for under between with".split()
)


def _mirrors(question, answer):
    """Whether an answer's opening sentence (after "Yes,"/"No,") restates the question's subject: at least
    half the question's content words are among its first 15 words."""
    words = [_stem(w) for w in re.findall(r"[a-z0-9']+", question.lower())]
    content = {w for w in words if w not in QUESTION_WORDS and w not in KEYWORD_FILLER}
    opening = {_stem(w) for w in re.findall(r"[a-z0-9']+", answer.lower())[1:16]}
    return bool(content) and len(content & opening) >= 0.5 * len(content)


def _comma_for_colon(heading):
    """One comma and no list word: a topic and its qualifier ("Worked Example, Acetone SDS"), which the house
    style separates with a colon; a comma in a heading only lists items. Not a question ("If an SDS Is
    Missing, What Should You Do?"), a number ("1,000 Chemicals") or a heading that already has its colon."""
    plain = re.sub(r"\d,\d", "", re.sub(r"\s*\{#[^}]*\}\s*$", "", heading)).strip()
    return (
        plain.count(",") == 1
        and not plain.endswith("?")
        and ":" not in plain
        and not re.search(r"(?i)\b(?:and|or)\b|&", plain)
    )


def _tacked_on_keyword(headings, pk, minimum=3):
    """Headings that end in the same connective plus the keyword ("… for How to Read a Safety Data Sheet",
    "… on SDS Retention Requirements"), at least `minimum` of them: the mechanical stuffing a model produces
    when told to put the keyword in a heading."""
    tails = {}
    pattern = re.compile(r"(?i)\b(?:for|on|about|in|with|of|and)\s+" + re.escape(pk) + r"\W*$")
    for heading in headings:
        plain = re.sub(r"\*+", "", heading).strip()
        if pattern.search(plain) and plain.lower().strip("?.! ") != pk.lower():
            tails.setdefault(pattern.search(plain).group(0).lower().split()[0], []).append(heading)
    worst = max(tails.values(), key=len, default=[])
    return worst if len(worst) >= minimum else []


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
    findings += _dropped_keywords_back(text, "Keyword and Anchor Map", ctx)
    lines = _headings_only(text)
    pk = (ctx.get("pkeyword") or "").lower()
    if not lines:
        findings.append(Finding("block", "the Headings-Only Outline has no `H1:`/`H2:`/`H3:` lines"))
        return findings
    prof = profile_of(ctx)
    if not lines[0].startswith("H1:"):
        findings.append(Finding("block", "the Headings-Only Outline must start with the `H1:` line"))
    if prof["key_takeaways"] != "none" and (len(lines) < 2 or lines[1].lower() != "h2: key takeaways"):
        findings.append(Finding(prof["key_takeaways"], "the second heading line must be `H2: Key Takeaways`"))
    h2s = [line for line in lines if line.startswith("H2:")]
    has_faq = bool(h2s) and h2s[-1].lower() == "h2: frequently asked questions"
    if not has_faq and prof["faq"] != "none":
        findings.append(Finding(prof["faq"], "the last H2 must be `H2: Frequently Asked Questions`"))
    if has_faq:
        faq_index = lines.index(h2s[-1])
        faq_h3 = [line for line in lines[faq_index + 1 :] if line.startswith("H3:")]
        if not 3 <= len(faq_h3) <= 7:
            findings.append(
                Finding(
                    "advise", f"{len(faq_h3)} FAQ question(s) under the FAQ heading; the SOP asks for 3-7"
                )
            )
    closing = h2s[-2] if has_faq and len(h2s) >= 2 else (h2s[-1] if h2s and not has_faq else "")
    if prof["close_heading"] == "cta" and closing and closing[3:].strip().lower() in GENERIC_CLOSE:
        findings.append(
            Finding(
                "block",
                f"the conclusion heading '{closing[3:].strip()}' is generic; use a verb-first CTA heading",
            )
        )
    body_h2s = [
        line for line in h2s if line.lower() not in ("h2: key takeaways", "h2: frequently asked questions")
    ]
    # A host that structures with H3s only (the approved HazCom guest post) still has sections.
    sections = (
        body_h2s if prof["close_heading"] == "cta" else [ln for ln in lines[1:] if ln[:3] in ("H2:", "H3:")]
    )
    if len(sections) < 3:
        findings.append(
            Finding("block", f"only {len(sections)} body section(s); a competitive article needs at least 3")
        )
    if prof["title_verbatim"] and ctx.get("title") and _title_key(lines[0][3:]) != _title_key(ctx["title"]):
        findings.append(
            Finding(
                "block",
                f"the `H1:` line must be the brief's title, kept word for word: '{ctx['title'].strip()}'",
            )
        )
    elif pk:
        h1_options = (_section_body(text, "H1 Options") or "").lower()
        if pk not in h1_options and pk not in lines[0].lower():
            findings.append(
                Finding(
                    prof["keyword_in_title"], f"no H1 option carries the primary keyword '{ctx['pkeyword']}'"
                )
            )
    if pk:
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
    """The text between the H1 and the first section heading (H2, or H3 where a host uses only H3s, as the
    approved HazCom guest post does)."""
    body = re.sub(r"(?m)^#\s+.*\n?", "", text, count=1)
    return re.split(r"(?m)^#{2,3}\s", "\n" + body, maxsplit=1)[0]


def _sentences(text):
    return [s for s in re.split(r"(?<=[.!?])\s+", " ".join(text.split())) if len(s.split()) > 2]


def _faq(text):
    body = _section_body(text, "Frequently Asked Questions")
    if body is None:
        return None, []
    items = re.split(r"(?m)^###\s+", body)[1:]
    return body, items


def profile_of(ctx):
    """The content type's check profile (types.yaml `checks`): which components exist and how strictly."""
    return ctx.get("profile") or prompting.check_profile(ctx.get("content_type") or "seo_blog")


def _title_key(text):
    return re.sub(r"[^a-z0-9]+", " ", re.sub(r"\*+", "", text or "").lower()).strip()


SCOPE_SENTENCE = re.compile(r"(?i)\b(?:in )?this (?:article|guide|post|piece)\b|\bwalk you through\b")


def check_article(text, ctx, *, metadata=True):
    findings = _mechanics(text)
    prof = profile_of(ctx)
    pk = (ctx.get("pkeyword") or "").lower()
    h1s = re.findall(r"(?m)^#\s+(.+)$", text)
    if len(h1s) != 1:
        findings.append(
            Finding("block", f"{len(h1s)} H1 heading(s); the article needs exactly one", level="structural")
        )
    elif prof["title_verbatim"] and ctx.get("title") and _title_key(h1s[0]) != _title_key(ctx["title"]):
        # A guest post keeps the sheet's title word for word (only its case may follow the host).
        findings.append(
            Finding(
                "block",
                f"the H1 must be the brief's title, kept word for word: '{ctx['title'].strip()}'",
                allows={"rename": [h1s[0]]},
            )
        )
    elif pk and pk not in h1s[0].lower():
        # On a guest post the outbound skill says flag a missing keyword once and never rewrite the title
        # (both approved Fixture A guest posts lack it).
        findings.append(
            Finding(
                prof["keyword_in_title"],
                f"the H1 '{h1s[0]}' doesn't carry the primary keyword '{ctx['pkeyword']}'",
                allows={"rename": [h1s[0]]} if not prof["title_verbatim"] else {},
            )
        )
    intro = _intro(text)
    first_100 = " ".join(quality_review.prose(intro).split()[:100]).lower()
    if pk and pk not in first_100:
        findings.append(Finding("block", "the primary keyword isn't in the first 100 words"))
    if prof["scope_sentence"] == "required" and not re.search(
        r"(?i)\bthis article\b|\bwalk you through\b", intro
    ):
        findings.append(
            Finding("block", "the intro has no scope sentence with the literal words 'this article'")
        )
    elif prof["scope_sentence"] == "forbidden" and (scope := SCOPE_SENTENCE.search(intro)):
        # The outbound skill: state the core content as content, never "This article covers…".
        findings.append(
            Finding(
                "block",
                f"the intro announces the article ('{scope.group(0)}'); state the core content as content",
            )
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
    takeaways = prof["key_takeaways"]
    if not names or names[0].lower() != "key takeaways":
        if takeaways != "none":
            findings.append(
                Finding(
                    takeaways,
                    "`## Key Takeaways` must be the first H2, right after the intro",
                    level="structural",
                )
            )
    else:
        bullets = _items(sections[1][1])
        if not 3 <= len(bullets) <= 7:
            findings.append(
                Finding(
                    "advise" if takeaways == "none" else takeaways,
                    f"{len(bullets)} Key Takeaways bullet(s); the SOP asks for 3-7",
                )
            )
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
    # A heading's `{#anchor}` tag is markup, not words (it would read as a keyword or a comma's partner).
    headings = [re.sub(r"\s*\{#[^}]*\}\s*$", "", h) for h in re.findall(r"(?m)^#{2,3}\s+(.+)$", text)]
    if pk and not any(carries_keyword(h, pk) for h in headings):
        # On a guest post the outbound skill says flag the shortfall rather than bend a heading.
        findings.append(
            Finding(
                prof["keyword_in_heading"],
                "no H2 or H3 carries the primary keyword, even as a natural variant",
                allows={"rename": ["*"]},
            )
        )
    # H2/H3 commas are fixed mechanically (normalise); this still catches an H1 (a verbatim guest-post title
    # is exempt) and anything a revision reintroduces.
    titles = [] if prof["title_verbatim"] else h1s[:1]
    for heading in [*titles, *headings]:
        if _comma_for_colon(heading):
            findings.append(
                Finding(
                    "block",
                    f"the heading '{heading.strip()}' joins a topic and its qualifier with a comma; "
                    "use a colon (house style)",
                    allows={"rename": [heading.strip()]},
                )
            )
    # Stuffing is the keyword tacked onto headings ("… Explained for How to Read a Safety Data Sheet" on
    # every H2, run 20), not the keyword in many headings: approved articles carry it in most H2s naturally
    # (Fixture A: the published JSA article has it in 17 headings, FAQ questions included).
    if pk and (tacked := _tacked_on_keyword(headings, pk)):
        findings.append(
            Finding(
                "block",
                f"the primary keyword is tacked onto the end of {len(tacked)} headings; restore them to "
                "plain topic headings and keep the keyword where it reads naturally",
                allows={"rename": tacked},
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
        if prof["faq"] != "none":
            findings.append(
                Finding(prof["faq"], "no `## Frequently Asked Questions` section", level="structural")
            )
    else:
        if not 3 <= len(faq_items) <= 7:
            # Advisory: the published JSA article (Fixture A) carries 8 and was approved.
            findings.append(Finding("advise", f"{len(faq_items)} FAQ question(s); the SOP asks for 3-7"))
        if ":::faq" not in faq_body:
            findings.append(
                Finding(
                    "advise", "the FAQ isn't wrapped in a `:::faq` block, so the page gets no FAQ component"
                )
            )
        for item in faq_items:
            question, _, answer = item.partition("\n")
            answer = answer.strip()
            # A link in an FAQ answer is allowed (the owner's rule, over the skill's "no hyperlinks").
            if re.match(r"(?i)^(?:yes|no)[,.!]", answer) and not _mirrors(question, answer):
                # A bare Yes/No is one the question's subject doesn't follow ("Yes, a PCBU owes…" to "Does
                # WHS risk management apply…?"); "Yes, WHS risk management applies…" mirrors it (Fixture A).
                # Mirroring "No, X isn't required" as "X isn't required" drops the "No".
                findings.append(
                    Finding(
                        "block",
                        f"the FAQ answer to '{question.strip()[:60]}' opens with a bare Yes/No; "
                        "mirror the question's subject",
                        allows={"drop_negations": 1 if answer.lower().startswith("no") else 0},
                    )
                )
    body_names = [
        n
        for n in names
        if n.lower() not in ("key takeaways", "frequently asked questions", "references", "metadata options")
    ]
    if body_names and prof["close_heading"] == "cta":
        close = body_names[-1].strip().lower()
        if close in GENERIC_CLOSE or close.startswith("conclusion"):
            findings.append(
                Finding(
                    "block",
                    f"the closing heading '{body_names[-1]}' is generic; the SOP wants a verb-first CTA "
                    "heading naming the reader's task and outcome",
                    allows={"rename": [body_names[-1]]},
                )
            )
    if prof["product_close"] == "required" and body_names:
        # The blog close is gap → action → one product page (run 20 closed on a "Start Free Trial" label
        # with no link at all). An article or lead magnet is never the CTA target.
        close_links = INTERNAL_LINK.findall(_section_body(text, body_names[-1]) or "")
        if not close_links and not ctx.get("no_product"):
            findings.append(
                Finding(
                    "block",
                    f"the closing section '{body_names[-1]}' links no product page; link the one product "
                    "page the conclusion plan names, in the sentence that offers it"
                    + (f": {ctx['planned_product']}" if ctx.get("planned_product") else ""),
                )
            )
        elif all(ARTICLE_PATH.search(link) for link in close_links):
            findings.append(
                Finding(
                    "block",
                    "the close links an article; the CTA links a product page, never an article",
                    allows={"drop_urls": _links_in(" ".join(close_links))},
                )
            )
    # Only the draft keeps a References section: from review and edit on, the sources are kept apart from the
    # article (verify.finalise) and never published.
    if metadata and prof["references"] != "none" and _section_body(text, "References") is None:
        findings.append(Finding(prof["references"], "no `## References` section"))
    if (floor := prof["min_internal_links"]) and (n := len(INTERNAL_LINK.findall(text))) < floor:
        findings.append(
            Finding(
                "advise",
                f"{n} sdsmanager.com link(s); the SOP asks for at least {floor}, or a flagged shortfall",
            )
        )
    if prof["adjacent_anchors"] == "forbidden":
        # A guest-post rule (ehs-outbound-blog; H3s count as sections): the blog skill has none, and both
        # published Fixture A blogs link in adjacent sections.
        parts = _subsections(text)
        linked = [i for i, (_, body) in enumerate(parts) if INTERNAL_LINK.search(body)]
        pairs = [(a, b) for a, b in zip(linked, linked[1:], strict=False) if b - a == 1]
        if pairs:
            findings.append(
                Finding(
                    "block",
                    "sdsmanager.com anchors sit in two adjacent sections: "
                    + ", ".join(f"'{parts[a][0] or 'intro'}' and '{parts[b][0]}'" for a, b in pairs[:3]),
                    allows={
                        "drop_urls": [
                            u for a, _ in pairs for u in _links_in(parts[a][1]) if "sdsmanager" in u
                        ]
                    },
                )
            )
    findings += check_sourced_urls(text, ctx)
    findings += check_citations(text, ctx)
    for anchor in ctx.get("anchors") or []:
        url = anchor.get("url", "")
        # Exact URL match: the landing page "/uk/" is a prefix of every module page under it (Fixture A).
        if (
            url
            and (n := sum(link.rstrip("/") == url.rstrip("/") for link in re.findall(r"\]\(([^)\s]+)", text)))
            != 1
        ):
            findings.append(
                Finding(
                    "block",
                    f"the anchor '{anchor.get('text', '')}' → {url} appears {n} time(s); "
                    "the brief wants it exactly once",
                )
            )
    findings += check_brief_anchors(text, ctx, prof, body_names)
    for match in pointer_sentences(text)[:3]:
        # A pointer sentence is cut, never reworded, so its link may go with it (run 20 deadlocked here).
        # Up to three at once, so several don't burn several rounds.
        findings.append(
            Finding(
                "block",
                "a sentence exists only to point at another page: '"
                + match.strip()[:90]
                + "'; cut it, and link a noun phrase in a sentence that states the fact or the fix instead",
                allows={"drop_urls": _links_in(match)},
            )
        )
    for match in META_NARRATION.finditer(text):
        # "the PPE named in this section is the minimum" is about SDS Section 8 named earlier in the same
        # paragraph; "In this section, we look at…" opening a paragraph is narration.
        paragraph = text[text.rfind("\n\n", 0, match.start()) + 1 : match.end()]
        if re.search(r"\b(?:Section|Chapter|Part|Article|Schedule)\s+\d", paragraph):
            continue
        findings.append(Finding("block", f"meta narration: '{match.group(0)}'"))
        break
    words = _words(text)
    if pk and words:
        # Whole-word matches in the prose, not inside link targets ("sds" in sdsmanager.com, phase 6), as
        # occurrences per word. Fixture A decided the reading: metrics.py's keyword-words share puts both
        # approved blogs over the line (2.6% and 4.2%); occurrences per word tops out at 1.4% on them.
        prose_text = re.sub(r"\]\([^)]*\)", "]", text).lower()
        hits = len(re.findall(rf"(?<![\w-]){re.escape(pk)}(?![\w-])", prose_text))
        density = hits / words
        if density > 0.025:
            findings.append(
                Finding(
                    "block",
                    f"primary keyword density {density:.1%}; keep it under about 2%",
                    allows={"rename": ["*"]},
                )
            )
    target = ctx.get("wordcount")
    if target and words and not 0.6 * target <= words <= 1.7 * target:
        findings.append(Finding("advise", f"{words} words against a guide of {target}"))
    if metadata and (counts := ctx.get("metadata_counts")):
        short = [kind for kind, n in counts.items() if n < 3]
        if short:
            # A note for the log only: the options live outside the text, so no revision can act on it.
            findings.append(Finding("note", "fewer than three metadata options for: " + ", ".join(short)))
    findings += check_reverse_outline(text, ctx)
    return findings + check_skill_scripts(text)


def _subsections(text):
    """[(name, body)] split at every H2 and H3: the outbound skill counts H3s as sections for anchors."""
    parts = re.split(r"(?m)^#{2,3}\s+(.+)\n", text)
    return [("", parts[0])] + [(parts[i].strip(), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


def _same_url(a, b):
    return a.rstrip("/").lower() == b.rstrip("/").lower()


def check_brief_anchors(text, ctx, prof, body_names):
    """Guest posts (outbound skill): only the brief's anchors link sdsmanager.com, none sits in the close,
    and the first sits in the first 30% of the article."""
    if not prof["brief_anchors_only"] and prof["product_close"] != "forbidden":
        return []
    findings = []
    anchors = [a for a in ctx.get("anchors") or [] if a.get("url")]
    internal = [
        m.group(1) for m in re.finditer(r"\]\(((?:https?://)?(?:www\.)?sdsmanager\.com[^)\s]*)\)", text)
    ]
    if prof["brief_anchors_only"]:
        extra = sorted({u for u in internal if not any(_same_url(u, a["url"]) for a in anchors)})
        if extra:
            findings.append(
                Finding(
                    "block",
                    "sdsmanager.com link(s) that aren't the brief's anchors: "
                    + ", ".join(extra[:3])
                    + "; a guest post carries only its anchors",
                    allows={"drop_urls": extra},
                )
            )
    closing = [n for n in body_names if _norm(n) not in (_norm(FAQ_HEADING), _norm("References"))]
    if prof["product_close"] == "forbidden" and closing:
        in_close = _links_in(
            " ".join(u for u in INTERNAL_LINK.findall(_section_body(text, closing[-1]) or ""))
        )
        if in_close:
            findings.append(
                Finding(
                    "block",
                    f"an sdsmanager.com link sits in the close ('{closing[-1]}'); a guest post carries "
                    "none there",
                    allows={"drop_urls": in_close},
                )
            )
    if anchors and internal:
        first = min(
            (text.find(f"]({u}") for u in internal if any(_same_url(u, a["url"]) for a in anchors)),
            default=-1,
        )

        def body_words(part):  # the article's text, not its headings
            return len(re.sub(r"(?m)^#{1,6}\s.*$", "", quality_review.prose(part)).split())

        total = body_words(text)
        if first > 0 and total and body_words(text[:first]) > 0.3 * total:
            # A block: the outbound skill's rule, and both approved Fixture A guest posts with anchors keep it
            findings.append(
                Finding(
                    "block",
                    "the first brief anchor sits after the first 30% of the article; move it into an earlier "
                    "section on its topic",
                )
            )
    return findings


def _heading_terms(heading):
    words = re.findall(r"[a-z0-9]+", re.sub(r"\*+", "", heading or "").lower())
    return {_stem(w) for w in words if w not in KEYWORD_FILLER and w not in QUESTION_WORDS and len(w) > 2}


def _section_score(planned, written):
    """How well a written H2 covers a planned one: 1.0 for the same heading, else the share of the planned
    heading's terms it keeps (the writer may reword a heading; it may not drop the section's subject)."""
    if _norm(re.sub(r"^conclusion\W*", "", planned, flags=re.I)) == _norm(written) or _norm(planned) == _norm(
        written
    ):
        return 1.0
    plan, have = _heading_terms(planned), _heading_terms(written)
    return len(plan & have) / len(plan) if plan else 0.0


def _match_sections(planned, written, threshold=0.5):
    """One written heading per planned one: exact matches first, then the best-scoring unused heading."""
    matches, used = [None] * len(planned), set()
    pairs = sorted(
        ((_section_score(p, w), i, j) for i, p in enumerate(planned) for j, w in enumerate(written)),
        key=lambda pair: -pair[0],
    )
    for score, i, j in pairs:
        if score >= threshold and matches[i] is None and j not in used:
            matches[i] = j
            used.add(j)
    return matches


def check_reverse_outline(text, ctx):
    """The content-editing skill's reverse outline, done by script: the article's H2s against the approved
    outline's. A planned section with no written counterpart, or sections out of the planned order, is a
    structural finding (it goes back to the plan, not to a line revision). Advisory until the replay over
    stored runs shows it fires only on real gaps (docs/sop-audit.md)."""
    planned = ctx.get("planned_h2s")
    if not planned:
        return []
    written = [
        name
        for name, _ in _sections(text)[1:]
        if _norm(name) not in (_norm("Key Takeaways"), _norm(FAQ_HEADING), _norm("References"))
    ]
    matches = _match_sections(planned, written)
    findings = []
    if missing := [p for p, m in zip(planned, matches, strict=True) if m is None]:
        findings.append(
            Finding(
                "advise",
                "planned section(s) missing from the article (reverse outline): "
                + "; ".join(f"'{p}'" for p in missing[:4]),
                level="structural",
            )
        )
    found = [m for m in matches if m is not None]
    if found != sorted(found):
        findings.append(
            Finding(
                "advise",
                "the article's sections are out of the outline's order (reverse outline)",
                level="structural",
            )
        )
    return findings


MAX_FLOW_PROMPTS = 6  # the flow check's prompts go to the reviewer; more than a handful drowns the rubric


def pointer_sentences(text):
    """Sentences whose job is to point at another page. A LINK_CARRIER phrase counts only with a link in the
    sentence or "our" in it ("see our guide"): "refer to the SDS for the PPE it lists" and "workers learn
    more from a drill" are instructions and facts (docs/sop-audit.md, phase 6)."""
    found = []
    for match in LINK_CARRIER.finditer(text):
        sentence = match.group(0)
        # Only "refer to the …" and "learn more …" need the link or "our": they are also how instructions and
        # facts are phrased. "see the X resource" stays a pointer (the owner's own example).
        loose = re.match(r"(?i)(?:refer to the|learn more)\b", sentence)
        if not loose or "](" in sentence or re.search(r"(?i)\bour\b", sentence):
            found.append(sentence)
    return found


def _terminated(text):
    """Headings and list items ended with a full stop where they have none (link_check splits sentences)."""
    text = re.sub(r"(?m)^(#{1,6}\s+.*?[^.!?:\s])[ \t]*$", r"\1.", text)
    return re.sub(r"(?m)^(\s*(?:[-*+]|\d+[.)])\s+.*?[^.!?:\s])[ \t]*$", r"\1.", text)


def check_skill_scripts(text):
    """The skill's own deterministic link and flow checks (vendored `link_check.py` and
    `editorial_flow_check.py`). Link placement the skill bans blocks; the flow check's output is, in its
    own words, review prompts and not rewrite instructions, so it advises."""
    from apps.quality import scripts

    findings = []
    try:
        # List items and headings end in a full stop for link_check only, so two unpunctuated bullets with a
        # link each aren't read as one sentence with two links (phase 6).
        links = scripts.run_json("links", _terminated(text))
        flow = scripts.run_json("flow", text)
    except (scripts.ScriptError, OSError, ValueError) as error:
        return [Finding("note", f"the skill's link and flow checks didn't run: {error}")]
    banned = (
        ("two_links_one_sentence", "two links in one sentence"),
        ("consecutive_links", "two links back to back in one paragraph"),
    )
    for key, label in banned:
        for item in (links.get(key) or [])[:2]:
            # The fix removes or moves a link; the re-check of the revision makes sure it moved, not vanished
            # where a link is required (the close, a brief anchor).
            findings.append(
                Finding(
                    "block",
                    f"{label} (link_check): '{_one_line(item)}'",
                    allows={"drop_urls": _links_in(item)},
                )
            )
    pointers = [_one_line(p, 60) for p in pointer_sentences(text)]
    for item in (links.get("link_only_sentences") or [])[:2]:
        # link_check's link-only test ("for more", four words or fewer) also fires on "[SDS software](…) keeps
        # every sheet current", the product-link form the rubric asks for: it blocks only where the
        # pointer-sentence check agrees (that finding is raised there), and otherwise prompts a read.
        if not any(p[:40] in _one_line(item, 200) for p in pointers):
            findings.append(
                Finding(
                    "advise",
                    f"a sentence that may be little more than its link (link_check): '{_one_line(item)}'",
                )
            )
    for heading, count in links.get("sections_over_one_internal") or []:
        # Advisory: both published Fixture A blogs carry two or three in a section (link_check counts H3s
        # as sections too).
        findings.append(
            Finding("advise", f"'{heading}' has {count} sdsmanager.com links; one per section (link_check)")
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


def dropped_keywords(step):
    """{keyword: why} the Search results step's keyword filter dropped (its version metrics)."""
    search = step.run.steps.filter(key="search_results").first()
    version = search.latest_version if search else None
    return dict(((version.metrics or {}).get("keywords") or {}).get("dropped") or {}) if version else {}


def context_from(step):
    brief = step.run.brief
    counts = {}
    for kind in ("title", "meta", "slug", "tags", "excerpt"):
        counts[kind] = step.run.metadata_options.filter(kind=kind).count()
    localise = step.key == "localise"
    return {
        # A localised variant translates the keyword (localise.md), so the source keyword isn't checked.
        "pkeyword": "" if localise else brief.pkeyword,
        "skeywords": [] if localise else list(brief.skeywords or []),
        "fkgl": float(brief.fkgl),
        "wordcount": brief.wordcount,
        "region": (brief.localise_to or brief.region) if localise else brief.region,
        "content_type": brief.content_type,
        "profile": prompting.check_profile(brief.content_type),
        # The title is kept word for word only when it came from the brief sheet (a typed topic isn't one).
        "title": brief.topic if brief.source_reference else "",
        "cta_style": brief.cta_style,
        "anchors": list(brief.anchors or []),
        "metadata_counts": counts if step.key == "draft" else {},
        "allowed_urls": allowed_urls(step),
        "allowed_citations": allowed_citations(step) if step.key in ARTICLE_STEPS else None,
        "dropped_keywords": dropped_keywords(step) if step.key in ("research", "outline") else {},
        **(outline_plan(prompting.approved_output(step.run, "outline")) if step.key in ARTICLE_STEPS else {}),
    }


NO_PRODUCT = re.compile(
    r"(?i)\bno (?:registry |honest |suitable )?product\b|\bnone (?:fits|applies)\b|\bno honest fit\b"
    r"|\bwithout (?:a )?product\b"
)


def outline_plan(outline):
    """What an article is checked against from its approved outline: the planned body H2s (the reverse
    outline, docs/sop-audit.md) and whether the Conclusion Plan says no product honestly fits (the skill's
    "No honest fit, no product": the close then needs no product link)."""
    if not outline:
        return {}
    planned = [
        line[3:].strip()
        for line in _headings_only(outline)
        if line.startswith("H2:") and _norm(line[3:]) not in (_norm("Key Takeaways"), _norm(FAQ_HEADING))
    ]
    conclusion = _section_body(outline, "Conclusion Plan") or ""
    product = next((u for u in _links_in(conclusion) if "sdsmanager.com" in u), "")
    return {
        "planned_h2s": planned,
        "no_product": bool(NO_PRODUCT.search(conclusion)),
        # The concrete value a finding hands the reviser ("link the page the plan names" alone isn't enough).
        "planned_product": product.rstrip(".,;:)"),
    }


FAQ_HEADING = "Frequently Asked Questions"


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
                # Hand the reviser the subsections it may cite for the same standard (the concrete value).
                same = sorted(s for s in allowed if s.startswith(match.group(1)))[:6]
                findings.append(
                    Finding(
                        "block",
                        f"the regulation reference {match.group(0).strip()} isn't in the research or the "
                        "search results; cite only subsections the inputs give"
                        + (f" (for this standard: {', '.join(same)})" if same else "")
                        + ", or keep the claim and add [VERIFY] before the sentence's full stop",
                        allows={"drop_spans": [match.group(0).strip(), match.group(1)]},
                    )
                )
    return findings


INVENTED_CITATION = re.compile(r"\[block\] the regulation reference (.+?) isn't in the research")
MARKER_VERIFY = house.MARKER_PATTERNS["VERIFY"]


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
    sources = [
        houseref.related_articles_block(brief),
        houseref.product_pages_block(brief.region),
        " ".join(a.get("url", "") for a in (brief.anchors or [])),
        prompting.approved_output(run, "search_results"),
        prompting.approved_output(run, "research"),
        prompting.approved_output(run, "outline"),
        brief.notes or "",
    ]
    if step.key == "localise" and brief.localise_to:
        # The variant links the target region's pages: a correct /uk/ link isn't an invented URL.
        target = copy.copy(brief)
        target.region = brief.localise_to
        sources += [houseref.related_articles_block(target), houseref.product_pages_block(brief.localise_to)]
    return sources


def _url_key(url):
    if "sdsmanager.com" not in url:
        return url
    return house.canonical_sds_url(url).split("#", 1)[0]


def check_sourced_urls(text, ctx):
    """Block findings for sdsmanager.com and wagtail links that don't come from the inputs."""
    allowed = ctx.get("allowed_urls")
    if allowed is None:
        return []
    findings = []
    seen = set()
    # Compared in canonical form (scheme, www, trailing slash, no fragment), as the mechanics write links.
    allowed_keys = {_url_key(u) for u in allowed}
    for url in URL.findall(text):
        url = url.rstrip(".,;:")
        own = "sdsmanager.com" in url or url.startswith("wagtail://")
        if (
            not own
            or _url_key(url) in allowed_keys
            or _url_key(url) in seen  # one finding per page, however it is spelled
            or re.match(r"wagtail://(?:page|document|image)\?id=\d+", url)
        ):
            continue
        seen.add(_url_key(url))
        findings.append(
            Finding(
                "block",
                f"the link {url} isn't in the inputs (invented URL); use a URL from the index, "
                "the product pages or the research, or drop the link",
                allows={"drop_urls": [url]},
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
    if step_key == "review_edit" and content_type:
        # The edit rubric says the guest-post draft rules still hold: include them, don't just name them.
        extra = f"{section(f'draft:{content_type}')}\n\n{extra}".strip()
    return f"{base}\n\n{extra}".strip() if extra else base


def parse_verdict(reply):
    """(verdict, findings, suggestions) from the reviewer's reply. Findings are the numbered items under
    "## Findings"; items under "## Suggestions" never block. A REVISE with no findings counts as PASS."""
    reply = reply or ""
    match = re.search(r"(?im)^\**\s*verdict\s*:?\**\s*:?\s*\**\s*(PASS|REVISE)", reply)
    verdict = match.group(1).upper() if match else ""
    findings, suggestions = [], []
    bucket = None  # items before any heading count as findings (a reply that skips the headings)
    for line in reply.splitlines():
        # "## Suggestions", "**Suggestions:**", "Suggestions:" all open a list.
        heading = re.match(r"(?i)^\s*(?:#{1,3}\s*)?\**\s*(findings?|suggestions?)\s*\**\s*:?\s*\**\s*$", line)
        if heading:
            bucket = suggestions if heading.group(1).lower().startswith("sugg") else findings
            continue
        item = re.sub(r"^\s*(?:\d+[.)]|[-*])\s+", "", line).strip()
        if not item or item == line.strip() or item.lower().startswith("verdict"):
            continue
        if re.fullmatch(r"(?i)\**none\.?\**", item):
            continue
        (findings if bucket is None else bucket).append(item[:400])
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
        search = prompting.approved_output(run, "search_results") or ""
        parts.append(("Search results the step saw", search.split("## Keyword data")[0], 3500))
        if "## Keyword data" in search:  # past the 3,500-character cut otherwise
            parts.append(
                ("Keyword data (kept and dropped, with why)", search.split("## Keyword data", 1)[1], 3000)
            )
        parts.append(("Published sdsmanager.com articles (internal index)", base_related(step), 600))
    if step.key in ARTICLE_STEPS and run.brief.content_type != "outbound":
        # The rubric judges links against these ("deepest relevant registry page", "URLs from the index").
        from . import houseref

        parts.append(("Published sdsmanager.com articles (internal index)", base_related(step), 600))
        parts.append(("SDS Manager product pages", houseref.product_pages_block(run.brief.region), 600))
    if step.key in ("outline", "draft"):
        parts.append(("Approved research", prompting.approved_output(run, "research"), 2500))
    if step.key == "draft":
        parts.append(("Approved outline", prompting.approved_output(run, "outline"), 2500))
    if run.brief.content_type == "outbound" and step.key in ("outline", "draft", "review_edit"):
        # Every host-style rubric line (case, nesting, tables, closing pattern) is judged against this.
        parts.append(("Approved site profile of the host", prompting.approved_output(run, "site_crawl"), 800))
    if step.key == "review_edit":
        parts.append(("The approved draft it edited", prompting.approved_output(run, "draft"), 2500))
    if step.key == "localise":
        source = prompting.approved_output(run, "review_edit") or prompting.approved_output(run, "draft")
        parts.append(("The approved article it localised", source, 2500))
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


def region_swap(step):
    """(source slug, target slug) for a localise step: its links move from /us/ to /uk/ by design."""
    from . import houseref

    brief = step.run.brief
    if step.key != "localise" or not brief.localise_to:
        return None
    return houseref.REGION_SLUGS.get(brief.region, "us"), houseref.REGION_SLUGS.get(brief.localise_to, "us")


def _guard(step_key, before, after, droppable=(), allows=None, swap=None):
    """Whether a revision may replace the text: the fixed invariants, minus exactly what the findings sent
    to the reviser allow (`allows`, from `permissions()`; `droppable` is the older name for drop_urls).

    An edited or localised article keeps every protected span (the skill's rule for rewriting approved
    prose). A draft is still being written, so its revision only has to keep the sections, most of the
    words, every link and every negation. A plan keeps its section names (the SOP's required sections)."""
    allows = allows or permissions([])
    for span in sorted({*droppable, *allows["drop_urls"], *allows["drop_spans"]}, key=len, reverse=True):
        before = before.replace(span, "")
    if swap:
        before = re.sub(rf"(sdsmanager\.com)/{swap[0]}/", rf"\1/{swap[1]}/", before)
    if step_key in ("review_edit", "localise"):
        ok, reason = quality_review.accept_rewrite(
            before, after, negation_allowance=allows["drop_negations"], localise=step_key == "localise"
        )
        if not ok:
            return ok, reason
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
        if lost > max(unfolded, 0) + allows["drop_negations"]:
            return False, "it dropped a negation (no, not, never…), which can reverse a claim"
    names_before = [name for name, _ in _sections(before) if name]
    names_after = [name for name, _ in _sections(after) if name]
    kept = {_norm(name) for name in names_after}
    lost = [name for name in names_before if _norm(name) not in kept]
    renamable = {_norm(name) for name in allows["rename"]}
    if "*" in allows["rename"] and step_key in ARTICLE_STEPS:
        lost = []  # a finding asks for headings to be reworded (keyword placement, stuffing, density)
    lost = [name for name in lost if _norm(name) not in renamable]
    if lost and step_key in ARTICLE_STEPS and len(names_after) == len(names_before):
        # An article heading may be reworded in place when count and order stay (run 20); plan section
        # names stay fixed (near misses are matched mechanically by canonical_section_names).
        lost = []
    if lost:
        return False, "it dropped or renamed the section(s) " + ", ".join(f"'{n}'" for n in lost[:4])
    if len(re.findall(r"(?m)^#{1,3}\s+.+$", after)) < len(re.findall(r"(?m)^#{1,3}\s+.+$", before)):
        return False, "sections were dropped"
    return True, ""


def introduced(before_checks, after_checks):
    """Kinds of blocking finding a revision added, or made more frequent: the whack-a-mole run 20 showed (a
    new invented URL every round). A revision that introduces any is refused."""
    count = Counter(check_kind(f) for f in before_checks if f.severity == "block")
    after = Counter(check_kind(f) for f in after_checks if f.severity == "block")
    return sorted(kind for kind, n in after.items() if n > count.get(kind, 0))


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


def normalise_plan_headings(text, required=None):
    """Plans sometimes come back with bold labels instead of headings ("**Search Intent**"). A line that is
    only a bold label becomes a `## ` heading, so the section checks, the reviewer and the exports read it.
    Lines that carry `H2:`/`H3:` plan markers are left to the headings-only parser. With `required`, only a
    label that names a required section is promoted: a sub-label inside a section ("**Regulatory claims**"
    under Claims) would otherwise split it and empty it. Returns (text, count)."""
    wanted = {_canon(name) for name in required or ()}

    def heading(match):
        label = match.group(1).strip().rstrip(":")
        if re.match(r"(?i)^H[1-4]\s*:", label):
            return match.group(0)
        key = _canon(label)
        if wanted and not (
            key in wanted or any(difflib.SequenceMatcher(None, key, k).ratio() >= 0.88 for k in wanted)
        ):
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


BOLD_HEADING = re.compile(r"(?m)^(#{1,6})\s+\*\*(.+?)\*\*[ \t]*$")
# Article headings models write for the fixed components, mapped to the names the checks and the publish
# step read (docs/sop-audit.md, phase 4).
HEADING_VARIANTS = (
    (
        re.compile(
            r"(?im)^##\s+(?:faqs?|frequently asked questions\s*\(faqs?\)|common questions)"
            r"\s*:?\s*(\{#[^}]*\})?\s*$"
        ),
        "## Frequently Asked Questions",
    ),
    (
        re.compile(
            r"(?im)^##\s+(?:sources|source list|reference list|references and sources|bibliography"
            r"|works cited)\s*:?\s*$"
        ),
        "## References",
    ),
)
FIRST_H2_TAKEAWAYS = re.compile(r"(?i)^(?:key points|key takeaway|takeaways|tl;?\s?dr|at a glance)\s*:?\s*$")


def normalise_article_headings(text):
    """FAQs/FAQ → Frequently Asked Questions, Sources/Bibliography → References, a first-H2 "Key Points" or
    "TL;DR" → Key Takeaways, and an FAQ section with `###` questions but no `:::faq` fence gets one (the
    page's FAQ component reads the fence). Returns (text, {fix: count})."""
    fixes = {}
    for pattern, replacement in HEADING_VARIANTS:
        text, n = pattern.subn(replacement, text)
        if n:
            fixes["component headings named"] = fixes.get("component headings named", 0) + n

    # "Worked Example, Acetone SDS" → "Worked Example: Acetone SDS": the same test as the comma check, whose
    # 11 distinct firings on runs 18-21 were all real; a script does it without a model round.
    def colon(match):
        heading = match.group(2)
        if _comma_for_colon(heading):
            fixes["heading commas made colons"] = fixes.get("heading commas made colons", 0) + 1
            # The first comma that isn't between digits ("1,000" stays).
            return match.group(1) + re.sub(r"(?<!\d),|,(?!\d)", ":", heading, count=1)
        return match.group(0)

    text = re.sub(r"(?m)^(#{2,3}\s+)(.+?)[ \t]*$", colon, text)
    first = re.search(r"(?m)^##\s+(.+?)\s*$", text)
    if first and FIRST_H2_TAKEAWAYS.match(first.group(1)):
        text = text[: first.start()] + "## Key Takeaways" + text[first.end() :]
        fixes["component headings named"] = fixes.get("component headings named", 0) + 1
    faq = re.search(r"(?ms)^## Frequently Asked Questions\s*\n(.*?)(?=^## |\Z)", text)
    if faq and ":::faq" not in faq.group(1) and re.search(r"(?m)^###\s", faq.group(1)):
        body = faq.group(1).strip()
        text = text[: faq.start(1)] + f"\n:::faq\n{body}\n:::\n\n" + text[faq.end(1) :]
        fixes["FAQ wrapped in :::faq"] = 1
    return text, fixes


def normalise(step_key, text):
    """Everything a script fixes better than a model, run before every check round (and by the replay
    harness, so it measures exactly what the loop sees). Returns (text, {fix: count})."""
    # House mechanics: dashes, curly quotes, emoji, rules, spacing, markers, broken links.
    text, fixes = house.mechanical_fix(text)
    # "## **Key Takeaways**": the CMS and Google Docs exports bold every heading; a heading is bold already.
    text, bolded = BOLD_HEADING.subn(r"\1 \2", text)
    if bolded:
        fixes["bold removed from headings"] = bolded
    if step_key in PLAN_STEPS:
        required = RESEARCH_SECTIONS if step_key == "research" else OUTLINE_SECTIONS
        text, promoted = normalise_plan_headings(text, required)
        if promoted:
            fixes["bold labels made headings"] = promoted
        text, renamed = canonical_section_names(text, required)
        if renamed:
            fixes["section names matched to the SOP"] = renamed
    text, fixed = normalise_fixed_headings(text)
    if fixed:
        fixes["fixed component headings"] = fixed
    if step_key in ARTICLE_STEPS:
        text, named = normalise_article_headings(text)
        for fix, n in named.items():
            fixes[fix] = fixes.get(fix, 0) + n
        # "Tags: …" / "Excerpt: …" lines under the H1 would publish as intro text.
        text, stray = textclean.strip_metadata_lines(text)
        if stray:
            fixes["metadata lines taken out of the article"] = sum(map(len, stray.values()))
    return text, fixes


def check_kind(finding):
    """A stable name for the check that produced a finding: its text with quoted parts, numbers and URLs
    blanked ("the heading '…' joins a topic…"). Used to count firings per check across runs and fixtures."""
    text = str(finding.text if isinstance(finding, Finding) else finding)
    text = re.sub(r"^\[(?:block|advise|note)\]\s*", "", text)
    # A quoted part may hold apostrophes ("doesn't", "SDS's"): an apostrophe between letters doesn't close it.
    text = re.sub(r"'(?:[^'\n]|(?<=\w)'(?=\w))*'|\"[^\"]*\"|“[^”]*”", "'…'", text)
    text = re.sub(r"(?:https?|wagtail)://\S+", "<url>", text)
    text = re.sub(r"\b\d[\d.,%]*\b", "N", text)
    return re.sub(r"\s+", " ", text).strip()[:90]


def measurements(step_key, text, ctx):
    """What the reviewer may judge the reading grade and length from (it is told to judge them from nothing
    else): article FKGL against the target, sentence-length flatness, words against the guide, and the
    sections more than a grade above target."""
    if step_key not in ARTICLE_STEPS:
        return ""
    target = ctx.get("fkgl")
    metrics = quality_review.article_metrics(text, target)
    line = f"\nMeasured by script (estimates): article FKGL {metrics['fkgl']}"
    line += f" against a target of {target:g}" if target else ""
    line += (
        f" ({metrics['words_per_sentence']} words a sentence, "
        f"{metrics['syllables_per_word']} syllables a word"
        f"; {len(metrics['hard'])} hard and {len(metrics['very_hard'])} very hard sentences)"
    )
    line += f"; sentence lengths {'look flat' if metrics['flat'] else 'vary'}; {metrics['words']} words"
    line += f" against a guide of {ctx['wordcount']}" if ctx.get("wordcount") else ""
    lines = [line + "."]
    over = [
        f"'{name}' {grade}"
        for name, grade in quality_review.section_grades(text)
        if grade and target and grade > target + 1
    ]
    if over:
        lines.append(
            "Sections more than a grade above target: "
            + "; ".join(over[:8])
            + ". Legal and domain terms may "
            "keep a section a grade or two above target; judge only syntax the writer could unpack."
        )
    return "\n".join(lines) + "\n"


def run_loop(step, text, call, max_rounds=None, verified=()):
    """The review-revise loop. `call(prompt_name, context, task)` returns (text, "provider/model").
    `verified` are claims the edit step confirmed against a source (verify.py): the regulation
    subsections they cite may stay, as the citation check otherwise allows only the inputs' ones."""
    max_rounds = settings.STUDIO_SOP_MAX_ROUNDS if max_rounds is None else max_rounds
    ctx = context_from(step)
    if ctx.get("allowed_citations") is not None:
        for claim in verified:
            if claim.get("verdict") in ("SUPPORTED", "CONTRADICTED"):
                sentence = claim.get("corrected") or claim.get("sentence") or ""
                ctx["allowed_citations"] |= {_citation(m) for m in CITATION.finditer(sentence)}
    base = prompting.context_for(step)
    result = SopResult(text=text, passed=False)
    inputs = _inputs_for(step)
    rejection = ""
    best = None  # (score, text, round number)
    for number in range(1, max_rounds + 2):
        current = Round(number)
        result.rounds.append(current)
        result.text, current.fixes = normalise(step.key, result.text)
        checks = check(step.key, result.text, ctx)
        current.checks = [str(f) for f in checks]
        reply, reviewer = call(
            "sop_review",
            {
                **base,
                "step_label": step.label,
                "rubric": rubric(step.key, step.run.brief.content_type),
                "inputs": inputs,
                # Two lists (docs/sop-audit.md, cause 4): blocks are verified; advisories are prompts to read.
                "checks": "\n".join(f"- {f.text}" for f in checks if f.severity == "block") or "- (none)",
                "prompts": "\n".join(f"- {f.text}" for f in checks if f.severity == "advise") or "- (none)",
                "measurements": measurements(step.key, result.text, ctx),
                "output": result.text,
            },
            "sop_review",
        )
        result.reviewer = reviewer
        current.verdict, current.findings, current.suggestions = parse_verdict(reply)
        block_findings = [f for f in checks if f.severity == "block"]
        blocking = [str(f) for f in block_findings]
        # Keep the best text seen: fewest blocks, then fewest reviewer findings (a later round can be worse).
        score = (len(blocking), len(current.findings))
        if best is None or score <= best[0]:
            best = (score, result.text, number)
        if current.verdict == "PASS" and not blocking:
            result.passed = True
            break
        # Route by level (docs/sop-audit.md): strategy and structure aren't fixed by a line revision. The
        # reviewer tags its own findings [strategic] / [structural]; the checks carry `level`.
        said = {tag: [f for f in current.findings if f.lower().startswith(f"[{tag}]")] for tag in LEVELS}
        if strategic := [str(f) for f in block_findings if f.level == "strategic"] + said["strategic"]:
            result.route, result.routed = "hold", strategic
            current.revision = "not revised: a strategic finding needs a person"
            break
        article = step.key in ARTICLE_STEPS
        structural = [f for f in block_findings if f.level == "structural" and article]
        reviewer_structural = said["structural"] if article else []
        routed = [str(f) for f in structural] + reviewer_structural
        result.route, result.routed = ("send_back", routed) if routed else ("", [])
        line_blocks = [f for f in block_findings if f not in structural]
        line_findings = [
            re.sub(r"(?i)^\[(?:structural|line)\]\s*", "", f)
            for f in current.findings
            if f not in reviewer_structural
        ]
        if number > max_rounds:
            break
        if not line_blocks and not line_findings:
            break  # only structural findings are left: they go back to the step, not to the reviser
        # Blocking checks always go; a handful of reviewer findings keeps the revision targeted.
        to_fix = [str(f) for f in line_blocks] + line_findings[:MAX_FINDINGS_PER_REVISION]
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
        # The revision gets the same mechanics before it is compared, so a model's "10–15" against the fixed
        # "10-15" isn't a changed fact; then the guard allows exactly what the findings sent allow.
        revised, _ = normalise(step.key, _strip_fences(revised))
        ok, reason = _guard(
            step.key, result.text, revised, allows=permissions(line_blocks), swap=region_swap(step)
        )
        if ok:
            revised_checks = check(step.key, revised, ctx)
            if new := introduced(checks, revised_checks):
                ok, reason = False, "it introduced new problems: " + "; ".join(new[:2])
            elif (
                current.verdict == "PASS"
                and blocking
                and (sorted(str(f) for f in revised_checks if f.severity == "block") == sorted(blocking))
            ):
                # The reviewer is satisfied and the revision didn't move a single block: more rounds won't.
                current.revision = "applied; the blocks it was asked to fix remain, so the loop stopped"
                result.text = revised.strip() + "\n"
                break
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
    if not result.passed and best and best[2] != len(result.rounds):
        # Hold on the best round's text, not the last one.
        result.text, result.best_round = best[1], best[2]
    return result


SEND_BACK_STEPS = ("draft", "localise")  # steps that regenerate from an approved plan or text


def _send_back(step, output, sop, call, executors):
    note = (
        "Your last attempt had these structural problems. Follow the approved outline's sections and order:\n"
        + "\n".join(f"- {finding.removeprefix('[block] ')}" for finding in sop.routed)
    )
    original = step.regenerate_note
    step.regenerate_note = f"{original}\n\n{note}".strip()
    try:
        retry = executors.EXECUTORS[step.key](step)
    finally:
        step.regenerate_note = original
    second = run_loop(step, retry.content, call)
    second.sent_back = True
    if (len(second.blocks()), not second.passed) <= (len(sop.blocks()), not sop.passed):
        return retry, second
    sop.sent_back = True
    return output, sop


def apply(step, output):
    """Run the loop on a StepOutput (apps.studio.executors) and fold the result into it."""
    from . import executors

    def call(prompt_name, context, task):
        messages = prompting.render(prompt_name, context)
        max_tokens = 4000 if task else executors.MAX_TOKENS.get(step.key, 8000)
        result = executors._call_text(step, messages, max_tokens=max_tokens, task=task)
        return result.text, f"{result.provider}/{result.model}"

    try:
        verified = ((output.extra_metrics or {}).get("verification") or {}).get("claims") or ()
        sop = run_loop(step, output.content, call, **({"verified": verified} if verified else {}))
        if sop.route == "send_back" and step.key in SEND_BACK_STEPS:
            # A structural defect isn't fixed by editing sentences: regenerate the step once from its plan
            # with the findings as the note, and keep whichever result is better.
            output, sop = _send_back(step, output, sop, call, executors)
    except (ProviderError, executors.StepError) as error:
        sop = SopResult(text=output.content, passed=False, error=executors.friendly_error(error))
    output.content = sop.text
    output.hold = output.hold or not sop.passed
    output.extra_metrics = {**(output.extra_metrics or {}), "sop": sop.as_metrics()}
    output.note = f"{output.note}\n\n{sop.note()}".strip() if output.note else sop.note()
    return output
