"""The review-and-edit sequence (docs/workflow.md), as the author runs it by hand:

1 scan the final draft → 2 /deslop rewrite → 3 /clarity-review rewrite → 4 auto-tune sections above the
target reading grade → 5 re-scan and report.

- Scanning uses the vendored skill scripts: deslop's lexical (with the ehs-seo-blog banned-word list and
  Title Case allowed, as that skill prescribes), structure and redundancy scans, clarity-review's frame
  scan, and the ehs-seo-blog metrics (FKGL and the sentence-length distribution).
- Reading grade follows the ehs-seo-blog rules: it's lowered by syntactic unpacking only; an edit that
  drops a section by more than MAX_GRADE_JUMP grades is accepted only if its sentence lengths aren't flat.
- A "section" is an H2 section, or, when an H2 section is longer than LONG_SECTION_WORDS and has H3s, its
  intro and each H3 subsection on their own, so a long section is tuned piece by piece. References,
  metadata and notes sections, tables and markers aren't graded.
- Every rewrite (here, in the suggestions chat and the Tune buttons) passes `accept_rewrite`: headings and
  most words kept, and protected spans (numbers, dates, section references, URLs, acronyms, markers) and
  negations preserved.

`call(prompt_name, context) -> str` is injected, so the sequence runs with any model and in tests.
"""

import re
from dataclasses import dataclass, field

from . import scripts

TUNE_TOLERANCE = 1.0  # sections more than this above the target are tuned
MAX_TUNED_SECTIONS = 10  # tuning calls per review, hardest sections first
LONG_SECTION_WORDS = 300
MAX_GRADE_JUMP = 1.5  # a bigger drop in one edit needs a healthy sentence-length mix
FLAT_RATIO = 0.7  # metrics.py: most sentences in one length band
MIN_SENTENCES_FOR_RHYTHM = 4  # a length mix can't be judged on fewer sentences
NOT_GRADED = {
    "references",
    "metadata options",
    "localisation notes",
    "localization notes",
    "deslop notes",
    "clarity edits",
}
BANNED_WORDS_TSV = scripts.VENDOR / "ehs_seo_blog" / "data" / "banned-words.tsv"

MARKER = re.compile(r"\[(?:VERIFY\b[^\]]*|SRC:[^\]]*|VISUAL:[^\]]*|HERO:[^\]]*)\]")
NEGATION = re.compile(
    r"\b(?:no|not|never|none|nor|cannot|without|can't|don't|doesn't|isn't|aren't|won't|wasn't|weren't|"
    r"shouldn't|mustn't|didn't|hasn't|haven't)\b",
    re.I,
)
# Negations a rewrite may remove because removing them is the fix: "not just X but Y", "not X but Y", and
# deslop's negative parallelism ("isn't about paperwork, it's about protecting workers"), the same pattern
# its lexical scan flags as the strongest machine-prose tell.
UNFOLDABLE_NEGATION = re.compile(
    r"\bnot (?:just|only|merely)\b|\bnot\b[^.!?\n]{0,80}?\bbut\b"
    r"|\b(?:isn't|is not|aren't|are not|it's not|wasn't)\b[^.!?\n]{0,70}?\b(?:it's|but|rather)\b",
    re.I,
)


@dataclass
class ReviewResult:
    text: str
    substeps: list = field(default_factory=list)
    grades: list = field(default_factory=list)  # [{heading, start, after_words, final}]
    proposals: list = field(default_factory=list)  # legacy split proposals (no longer generated)
    metrics: dict = field(default_factory=dict)  # whole-article before/after, slop index before/after
    questions: list = field(default_factory=list)  # deslop's substantive questions for the author
    clarity_edits: list = field(default_factory=list)


# ---- Sections ----


def split_sections(text):
    """[(heading_line, body)] where heading_line is '' for the intro; ''.join reassembles the text."""
    parts = re.split(r"(?m)^(##\s+.+\n)", text)
    sections = [("", parts[0])]
    for index in range(1, len(parts) - 1, 2):
        sections.append((parts[index], parts[index + 1]))
    return sections


def join_sections(sections):
    return "".join(heading + body for heading, body in sections)


def heading_name(heading_line):
    return heading_line.lstrip("#").strip() or "(intro)"


def section_units(text, max_words=LONG_SECTION_WORDS):
    """Like split_sections, but a long H2 section with H3s becomes its intro plus one unit per H3.
    ''.join reassembles the text exactly."""
    units = []
    for heading, body in split_sections(text):
        if len((heading + body).split()) <= max_words or not re.search(r"(?m)^###\s", body):
            units.append((heading, body))
            continue
        parts = re.split(r"(?m)^(###\s+.+\n)", body)
        units.append((heading, parts[0]))
        units += [(parts[i], parts[i + 1]) for i in range(1, len(parts) - 1, 2)]
    return units


def prose(text):
    """The part of a text whose reading grade means something: no tables, markers or FAQ fences."""
    lines = [
        line for line in text.splitlines() if not line.lstrip().startswith("|") and line.strip() != ":::faq"
    ]
    return MARKER.sub("", "\n".join(lines)).replace(":::", "")


def graded(heading):
    return heading_name(heading).lower() not in NOT_GRADED


def grading_text(text):
    """Prose as it is graded: headings left out and list items ended with a full stop. A heading without
    punctuation used to join the next sentence and an unpunctuated list became one long "sentence", so list
    sections read 2-4 grades high and were queued for tuning (docs/sop-audit.md, phase 7)."""
    text = re.sub(r"(?m)^#{1,6}\s.*$", "", prose(text))
    return re.sub(r"(?m)^(\s*(?:[-*+]|\d+[.)])\s+.*?[^.!?:;\s])[ \t]*$", r"\1.", text)


def grade(text):
    return scripts.fkgl(grading_text(text))


NATURAL_SENTENCE = 15  # words: a natural average; tuning below it means uniformly short sentences


def vocabulary_floor(text):
    """The grade a section's own words allow at a natural sentence length: FKGL = 0.39 x words per sentence
    + 11.8 x syllables per word - 15.59, with 15 words a sentence. EHS prose runs at about 1.7 syllables a
    word, so a target of 9 is out of reach without the banned uniform short sentences; the skill allows a
    grade or two above target where the terms require it. Tuning aims at max(target, floor)."""
    m = scripts.metrics_module()
    words = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", m.strip_markdown(grading_text(text)))
    if len(words) < 30:
        return None
    per_word = sum(m.count_syllables(w) for w in words) / len(words)
    return round(0.39 * NATURAL_SENTENCE + 11.8 * per_word - 15.59, 1)


STACKED_WORDS = 25  # a sentence this long usually stacks clauses


def stacked_sentences(text, limit=6):
    """The sentences worth unpacking: the longest ones over STACKED_WORDS words, in reading order."""
    m = scripts.metrics_module()
    found = [
        s for s in m.split_sentences(m.strip_markdown(grading_text(text))) if len(s.split()) > STACKED_WORDS
    ]
    keep = set(sorted(found, key=lambda s: -len(s.split()))[:limit])
    return [s for s in found if s in keep]


ARTICLES = {"the", "a", "an", "this", "that", "these", "those", "each", "every"}
PRONOUNS = {"it", "they", "you", "we", "he", "she", "its", "their", "your"}


def opener_run(text):
    """The longest run of consecutive sentences in one paragraph that open with the same subject words
    ("The operator… The operator… The operator…", the tuning tell from run 19)."""
    m = scripts.metrics_module()
    longest = 0
    for paragraph in re.split(r"\n\s*\n", grading_text(text)):
        openers = []
        for sentence in m.split_sentences(m.strip_markdown(paragraph)):
            words = [w.lower() for w in re.findall(r"[A-Za-z']+", sentence)]
            subject = next((w for w in words if w not in ARTICLES), "")
            # A pronoun callback ("It… It…") is the connected style the tuning prompt asks for, not the tell.
            openers.append("" if subject in PRONOUNS else subject)
        run = 1
        longest = max(longest, 1 if openers else 0)
        for previous, current in zip(openers, openers[1:], strict=False):
            run = run + 1 if current and current == previous else 1
            longest = max(longest, run)
    return longest


def unit_rows(text, target=None):
    """Per-section rows for the workspace's grade table: index, level, name, words, grade, over target."""
    rows = []
    for index, (heading, body) in enumerate(section_units(text)):
        value = grade(heading + body) if graded(heading) else None
        level = 3 if heading.startswith("###") else (2 if heading else 0)
        rows.append(
            {
                "index": index,
                "level": level,
                "name": heading_name(heading),
                "words": len(prose(body).split()),
                "grade": value,
                "graded": graded(heading),
                "over": bool(value and target is not None and value > float(target) + TUNE_TOLERANCE),
            }
        )
    return rows


def section_grades(text):
    return [(heading_name(h), grade(h + b) if graded(h) else None) for h, b in section_units(text)]


def article_text(text):
    """The article without its references, metadata and notes sections."""
    return join_sections([(h, b) for h, b in split_sections(text) if graded(h)])


def article_metrics(text):
    """Whole-article FKGL and sentence-length distribution, from the ehs-seo-blog metrics script."""
    m = scripts.metrics_module()
    sentences = m.split_sentences(m.strip_markdown(grading_text(article_text(text))))
    value, words, _ = m.fkgl(sentences)
    distribution = m.length_distribution(sentences) or {}
    return {
        "fkgl": round(value, 1) if words >= 30 else None,
        "words": words,
        "sentences": len(sentences),
        "buckets": distribution.get("buckets", {}),
        "flatness_ratio": distribution.get("flatness_ratio"),
        "flat": bool(distribution.get("flatness_ratio") and distribution["flatness_ratio"] >= FLAT_RATIO),
    }


def _sentences(text):
    m = scripts.metrics_module()
    return len(m.split_sentences(m.strip_markdown(prose(text))))


def _flatness(text):
    m = scripts.metrics_module()
    distribution = m.length_distribution(m.split_sentences(m.strip_markdown(prose(text)))) or {}
    return distribution.get("flatness_ratio") or 0


# ---- Accepting a rewrite ----


def _headings(text):
    return re.findall(r"(?m)^#{1,3}\s+.+$", text)


# What a number counts, when it says so: the unit stays with the number through a rewrite. Any other word
# after a number is free ("1910.1200 requires" may become "Under 1910.1200, employers must…"): protecting
# the next word refused every agent-and-verb rewrite after a regulation number (docs/sop-audit.md).
UNITS = (
    r"%|percent|per cent|ppm|ppb|mg/m3|mg/kg|mg|kg|g|lb|lbs|oz|t|tonnes?|tons?|m|cm|mm|km|ft|feet|foot|"
    r"inch(?:es)?|metres?|meters?|litres?|liters?|l|ml|gallons?|°[CF]|degrees?|years?|months?|weeks?|days?|"
    r"hours?|hrs?|"
    r"minutes?|mins?|seconds?|employees?|workers?|people|persons?|sites?|chemicals?|sections?|items?|steps?|"
    r"pages?|violations?|citations?|times|x"
)
NUMBER_WITH_UNIT = re.compile(rf"\d+(?:[.,:/-]\d+)*(?:\([a-z0-9]+\))*(?:\s?(?:{UNITS})\b|\s?%)?", re.I)
# A number written out keeps its unit too: "thirty years" turned into "ten years" passed every guard.
NUMBER_WORDS = (
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|"
    r"seventeen|eighteen|nineteen|twenty|thirty|forty|fifty|sixty|seventy|eighty|ninety|hundred|thousand|"
    r"million|half|dozen"
)
WORD_NUMBER_WITH_UNIT = re.compile(rf"\b(?:{NUMBER_WORDS})(?:[- ](?:{NUMBER_WORDS}))*\s(?:{UNITS})\b", re.I)


MARKER_VERIFY = re.compile(r"\[\s*VERIFY\b[^\]]*\]", re.I)
CITATION_NUMBER = re.compile(r"^\d{3,}\.\d|\(")  # "1910.1200", "1910.1200(h)": a regulation's id


def protected_spans(text, localise=False):
    """Things a rewrite must never change: numbers with the unit they count, section and regulation
    references, URLs, acronyms (agencies, statutes) and markers. A localised variant replaces the source
    region's regulators and citations by design (OSHA → HSE), so `localise` leaves acronyms, regulation
    references and citation numbers out; the region slug in URLs is mapped by the caller."""
    flat = re.sub(r"\s+", " ", text)
    numbers = {m.group(0).strip() for m in NUMBER_WITH_UNIT.finditer(flat)}
    spans = {n for n in numbers if not (localise and CITATION_NUMBER.search(n))}
    spans |= {m.group(0).strip().lower() for m in WORD_NUMBER_WITH_UNIT.finditer(flat)}
    if not localise:
        spans |= set(
            re.findall(
                r"\b(?:Section|Regulation|Part|Article|Schedule|Rule|Subpart|Appendix)\s+[\dA-Z][\w.()-]*",
                flat,
            )
        )
        spans |= set(re.findall(r"\b[A-Z]{2,}[A-Z0-9&]*\b", flat))
    spans |= set(re.findall(r"(?:https?|wagtail)://[^\s)\]]+", flat))
    spans |= set(MARKER.findall(flat))
    return spans


def protected_ok(before, after, negation_allowance=0, localise=False):
    """(ok, reason): every protected span survives, and no negation is lost (unfolding a 'not X but Y'
    into the positive claim may remove its 'not'; `negation_allowance` more may go when a finding's fix is
    exactly that, e.g. a bare "No," FAQ opener rewritten to mirror the question). A localised variant may
    change a figure only where it adds a [VERIFY] for it (the localisation rule: changed facts are marked)."""
    missing = sorted(protected_spans(before, localise) - protected_spans(after, localise))
    if missing and localise:
        added = len(MARKER_VERIFY.findall(after)) - len(MARKER_VERIFY.findall(before))
        figures = [s for s in missing if not s.startswith(("http", "wagtail", "["))]
        if len(figures) == len(missing) and added >= len(figures):
            missing = []
    if missing:
        shown = ", ".join(f"“{span}”" for span in missing[:5])
        return False, f"it changed or dropped protected facts: {shown}"
    lost = len(NEGATION.findall(before)) - len(NEGATION.findall(after))
    # Only an unfoldable "not X but Y" that actually disappeared may account for a lost negation.
    unfolded = len(UNFOLDABLE_NEGATION.findall(before)) - len(UNFOLDABLE_NEGATION.findall(after))
    if lost > max(unfolded, 0) + negation_allowance:
        return False, "it dropped a negation (no, not, never…), which can reverse a claim"
    return True, ""


def accept_rewrite(before, after, min_ratio=0.75, negation_allowance=0, localise=False):
    """A rewrite is kept only if it keeps every heading, most of the words and every protected fact."""
    after = (after or "").strip()
    if not after:
        return False, "empty output"
    if len(_headings(after)) < len(_headings(before)):
        return False, "headings were dropped"
    if len(after.split()) < min_ratio * len(before.split()):
        return False, "too much text was removed"
    return protected_ok(before, after, negation_allowance, localise)


_accept_rewrite = accept_rewrite  # older name, used by the chat


def split_notes(reply, heading):
    """Separate a trailing '## <heading>' list from a rewrite; returns (text, [items])."""
    match = re.search(rf"(?mi)^##\s+{re.escape(heading)}\s*$", reply or "")
    if not match:
        return (reply or "").strip(), []
    items = []
    for line in reply[match.end() :].splitlines():
        item = re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        if item and item.lower().rstrip(".") != "none":
            items.append(item)
    return reply[: match.start()].strip(), items


# ---- Tuning one section ----


def tune_unit(text, index, target, region, call):
    """Syntactic unpacking of one section towards `target`. Returns (new_text, before, after); raises
    ValueError with the reason when the edit isn't used."""
    units = section_units(text)
    if not 0 <= index < len(units):
        raise ValueError("That section no longer exists; reload the page.")
    heading, body = units[index]
    if not graded(heading):
        raise ValueError(f"“{heading_name(heading)}” isn't article prose, so it isn't tuned.")
    original = (heading + body).strip()
    before = grade(original)
    stacked = stacked_sentences(original)
    edited = (
        call(
            "review_wordlevel",
            {
                "section": original,
                "grade": before,
                "target": target,
                "region": region,
                "stacked": "\n".join(f"- {s}" for s in stacked)
                or "- (none over 25 words: unpack only where a clause stacks)",
            },
        )
        or ""
    ).strip()
    if heading and not edited.startswith("#"):
        edited = f"{heading.strip()}\n\n{edited}"
    ok, reason = accept_rewrite(original, edited, min_ratio=0.8)
    if not ok:
        raise ValueError(f"The rewrite wasn't used ({reason}).")
    # Refused when it repeats a subject down a paragraph ("The operator… The operator…"), the flat
    # unpacking run 19 produced, unless the original already did.
    if (run := opener_run(edited)) >= 3 and run > opener_run(original):
        raise ValueError(f"The rewrite opens {run} sentences in a row with the same subject (choppy).")
    after = grade(edited)
    if before is not None and after is not None:
        if after >= before:
            raise ValueError(f"The rewrite didn't lower the grade ({before} → {after}).")
        if (
            before - after > MAX_GRADE_JUMP
            and _sentences(edited) >= MIN_SENTENCES_FOR_RHYTHM
            and _flatness(edited) >= FLAT_RATIO
        ):
            raise ValueError(
                f"The grade dropped {before} → {after} in one edit and the sentences are now nearly all "
                "one length (choppy), which the house rules don't allow."
            )
    trailing = body[len(body.rstrip()) :] or "\n\n"
    units[index] = ("", edited + trailing)
    return join_sections(units).strip() + "\n", before, after


# ---- Sequence ----


def _record(result, number, name, changed, summary, **extra):
    result.substeps.append({"number": number, "name": name, "changed": changed, "summary": summary, **extra})


def _scan(name, text, *args):
    try:
        return scripts.run_json(name, text, *args)
    except (scripts.ScriptError, OSError):
        return None


def _lexical(text):
    args = ["--allow-title-case"]
    if BANNED_WORDS_TSV.exists():
        args += ["--wordlist", str(BANNED_WORDS_TSV)]
    return _scan("lexical", text, *args) or {}


def _terms(brief):
    words = [brief.get("pkeyword") or "", *(brief.get("skeywords") or [])]
    return ",".join(w for w in words if w)


def run_sequence(text, brief, call):
    target = float(brief.get("fkgl") or 9)
    result = ReviewResult(text=text.strip() + "\n")

    # 1. Scan the final draft.
    lexical, structure = _lexical(result.text), _scan("structure", result.text) or {}
    redundancy = _scan("redundancy", result.text) or {}
    start_metrics, start = article_metrics(result.text), section_grades(result.text)
    over = [name for name, value in start if value and value > target + TUNE_TOLERANCE]
    result.metrics = {"before": start_metrics, "slop_before": lexical.get("slop_index")}
    _record(
        result,
        1,
        "Scan",
        False,
        f"Slop index {lexical.get('slop_index', '–')} (uncalibrated triage, not evidence of authorship); "
        f"{len(lexical.get('findings') or [])} lexical and {len(redundancy.get('findings') or [])} "
        f"cross-section repetition finding(s). Article FKGL {start_metrics['fkgl']} "
        f"(estimate) against target "
        f"{target:g}; {len(over)} section(s) more than {TUNE_TOLERANCE:g} above it."
        + (" Sentence lengths look flat." if start_metrics["flat"] else ""),
    )

    # 2. Deslop rewrite.
    findings = _deslop_findings(lexical, structure, redundancy)
    # deslop: "structural and substantive surfaced as inline comments for the author", never applied by the
    # rewrite (forcing variance there is the banned equalising move). They go to the report.
    structural = _structure_notes(structure)
    _rewrite_pass(
        result,
        call,
        2,
        "Deslop rewrite",
        "review_deslop",
        {
            "findings": "\n".join(findings)
            or "(the scanners found nothing; check for the rewrite rules by reading)"
        },
        "Deslop notes",
        f"{len(findings)} scanner finding(s) addressed with the deslop rewrite rules."
        + (" For the author, not applied: " + "; ".join(structural) + "." if structural else ""),
    )

    # 3. Clarity-review rewrite.
    frames = (
        _scan("frames", result.text, "--terms", _terms(brief))
        if _terms(brief)
        else _scan("frames", result.text)
    )
    candidates = _clarity_candidates(frames or {})
    _rewrite_pass(
        result,
        call,
        3,
        "Clarity-review rewrite",
        "review_clarity",
        {"candidates": "\n".join(candidates) or "(no scan candidates; read for all ten defect types)"},
        "Clarity edits",
        f"Read for the ten clarity defect types ({len(candidates)} scan candidate(s)).",
    )
    after_edit = section_grades(result.text)

    # 4. Auto-tune sections above the target (syntactic unpacking).
    _auto_tune(result, call, brief, target)

    # 5. Re-scan and report.
    final_metrics, final = article_metrics(result.text), section_grades(result.text)
    lexical_after = _lexical(result.text)
    result.metrics.update(after=final_metrics, slop_after=lexical_after.get("slop_index"))
    still = [name for name, value in final if value and value > target + TUNE_TOLERANCE]
    _record(
        result,
        5,
        "Re-scan",
        False,
        f"Slop index {lexical.get('slop_index', '–')} → {lexical_after.get('slop_index', '–')}. Article FKGL "
        f"{start_metrics['fkgl']} → {final_metrics['fkgl']} (estimate); {len(still)} section(s) still more "
        f"than {TUNE_TOLERANCE:g} above target (use Tune, or accept it where legal terms set the floor)."
        + (" Sentence lengths look flat: vary cadence." if final_metrics["flat"] else ""),
    )
    result.grades = _grade_rows(start, after_edit, final)
    return result


def _deslop_findings(lexical, structure, redundancy):
    """The lexical and redundancy findings the rewrite acts on, each with the scanner's own fix (a class-A
    replacement and its condition, or a class-B "no substitute": a synonym swap is the failure mode).
    Low-severity findings (curly quotes, the tricolon count the script itself calls high-false-positive)
    are left out, as deslop's default --min-severity is medium. Structural findings are not here."""
    findings = []
    for finding in lexical.get("findings") or []:
        if finding.get("severity") == "low":
            continue
        examples = "; ".join(e.get("text", "").strip() for e in (finding.get("examples") or [])[:4])
        fix = " ".join(str(finding.get("fix") or "").split())
        findings.append(
            f"- {finding.get('id')} ({finding.get('severity')}, {finding.get('count')}×): {examples}"
            + (f" → {fix[:220]}" if fix else "")
        )
    for finding in (redundancy.get("findings") or [])[:6]:
        findings.append(f"- repeated across sections: {str(finding)[:200]}")
    return findings


def _structure_notes(structure):
    """structure_scan's findings as short notes for the author ("id=value"), never rewrite instructions."""
    notes = []
    for finding in (structure.get("findings") or [])[:6]:
        value = finding.get("value")
        notes.append(f"{finding.get('id', 'structure')}" + (f"={value}" if value is not None else ""))
    return notes


def _clarity_candidates(frames):
    candidates = []
    for item in (frames.get("bare_demonstratives") or [])[:12]:
        candidates.append(f"- unclear reference “{item.get('match')}”: {item.get('sentence', '')[:200]}")
    for item in (frames.get("placeholder_nouns") or [])[:8]:
        candidates.append(f"- vague noun “{item.get('match')}”: {item.get('sentence', '')[:200]}")
    for item in (frames.get("frames_over_threshold") or [])[:6]:
        candidates.append(f"- repeated sentence frame: {str(item)[:200]}")
    # frame_scan reports term usage under "term_drift" ({term: count}); the old keys never existed, so this
    # was never passed on (phase 7). Two or more of the brief's terms in use is a one-name-per-concept prompt.
    used = {term: n for term, n in (frames.get("term_drift") or {}).items() if n}
    if len(used) >= 2:
        candidates.append(
            "- names in use for related concepts (keep one name per concept): "
            + ", ".join(f"{term} ×{n}" for term, n in sorted(used.items(), key=lambda kv: -kv[1])[:6])
        )
    for item in (frames.get("orphan_possessives") or [])[:4]:
        text = item.get("sentence", item) if isinstance(item, dict) else item
        candidates.append(f"- possessive with no owner in the sentence: {str(text)[:200]}")
    for item in (frames.get("mixed_person_paragraphs") or [])[:4]:
        candidates.append(f"- mixed person in one paragraph near line {item.get('line')}")
    return candidates


def accept_by_section(before, after, min_ratio=0.75):
    """Accept a whole-article rewrite section by section: a section whose rewrite changed a protected fact or
    lost a negation goes back to its original, the others keep their edits. One refused span used to throw
    away every section's edits (docs/sop-audit.md). Falls back to the whole-article test when the rewrite
    changed the section structure. Returns (text, reverted [(section name, reason)]), or (None, reason)."""
    after = (after or "").strip() + "\n"
    old, new = split_sections(before), split_sections(after)
    if [heading_name(h) for h, _ in old] != [heading_name(h) for h, _ in new]:
        ok, reason = accept_rewrite(before, after, min_ratio)
        return (after, []) if ok else (None, reason)
    if len(after.split()) < min_ratio * len(before.split()):
        return None, "too much text was removed"
    kept, reverted = [], []
    for (heading, body), (new_heading, new_body) in zip(old, new, strict=True):
        if (heading + body).strip() == (new_heading + new_body).strip():
            kept.append((heading, body))
            continue
        # Facts and negations are judged per section; length only for the whole article, because deslop's
        # cuts are legitimately large in a short section ("cutting beats rewording").
        ok, reason = protected_ok(heading + body, new_heading + new_body)
        if ok:
            kept.append((new_heading, new_body))
        else:
            kept.append((heading, body))
            reverted.append((heading_name(heading), reason))
    if reverted and len(reverted) == sum(1 for o, n in zip(old, new, strict=True) if o != n):
        return None, "every changed section " + reverted[0][1].removeprefix("it ")
    return join_sections(kept), reverted


def _rewrite_pass(result, call, number, name, prompt, context, notes_heading, summary):
    before = result.text
    reply = call(prompt, {"article": before, **context}) or ""
    after, notes = split_notes(reply, notes_heading)
    text, reverted = accept_by_section(before, after)
    if text is None:
        notes = [f"(not applied: the rewrite was refused) {note}" for note in notes]
    elif reverted:
        notes.append(
            "Sections kept as they were: "
            + "; ".join(f"{section} ({reason})" for section, reason in reverted[:4])
            + ". Edits described above for those sections were not applied."
        )
    if notes_heading == "Deslop notes":
        result.questions = notes
    else:
        result.clarity_edits = notes
    if text is not None:
        result.text = text.strip() + "\n"
        detail = f" {len(notes)} note(s)." if notes else ""
        if reverted:
            detail += f" {len(reverted)} section(s) kept as they were (a protected fact or negation changed)."
        _record(result, number, name, text.strip() != before.strip(), summary + detail, notes=notes)
    else:
        _record(
            result, number, name, False, f"Rewrite not used ({reverted}); text left unchanged.", notes=notes
        )


def _keyed_units(text):
    """[((name, occurrence), (heading, body))] for the units of a text."""
    seen, keyed = {}, []
    for unit in section_units(text):
        name = heading_name(unit[0])
        seen[name] = seen.get(name, 0) + 1
        keyed.append(((name, seen[name]), unit))
    return keyed


def _auto_tune(result, call, brief, target):
    # Each section aims at max(target, its vocabulary floor): a section held up only by its terms isn't
    # tuned, because the only way under that floor is uniformly short sentences (phase 7).
    order, floored = [], []
    for key, (heading, body) in _keyed_units(result.text):
        value = grade(heading + body) if graded(heading) else None
        if not value:
            continue
        floor = vocabulary_floor(heading + body)
        aim = max(target, floor) if floor else target
        if value > aim + TUNE_TOLERANCE:
            order.append((value, key, aim))
        elif value > target + TUNE_TOLERANCE:
            floored.append(f"{key[0]} {value} (vocabulary floor {floor})")
    order.sort(reverse=True)
    changed, skipped = [], []
    for _, key, aim in order[:MAX_TUNED_SECTIONS]:
        # By name and occurrence, looked up afresh: two H3s with one name used to tune the wrong one, and a
        # tuned section can change how the long sections split into units.
        name = key[0]
        index = next((i for i, (k, _) in enumerate(_keyed_units(result.text)) if k == key), None)
        if index is None:
            continue
        try:
            result.text, before, after = tune_unit(result.text, index, aim, brief.get("region", ""), call)
            changed.append(f"{name}: {before} → {after}")
        except ValueError as error:
            skipped.append(f"{name}: {error}")
    summary = "; ".join(changed) if changed else f"No section more than {TUNE_TOLERANCE:g} above its aim."
    if floored:
        summary += " Left at their vocabulary floor (the terms set it): " + "; ".join(floored[:4]) + "."
    if skipped:
        summary += " Not changed: " + "; ".join(skipped[:4])
    if len(order) > MAX_TUNED_SECTIONS:
        summary += f" {len(order) - MAX_TUNED_SECTIONS} more section(s) left for the Tune buttons."
    _record(result, 4, "Reading grade by section (syntactic unpacking)", bool(changed), summary)


def _grade_rows(start, after_edit, final):
    """Line up grades per section. Rewrites can reword headings, so match by position when the
    number of sections is unchanged, otherwise by heading text."""
    if len(start) == len(after_edit) == len(final):
        return [
            {
                "heading": final[i][0],
                "start": start[i][1],
                "after_words": after_edit[i][1],
                "final": final[i][1],
            }
            for i in range(len(start))
            if final[i][1] is not None or start[i][1] is not None
        ]
    after_map, final_map = dict(after_edit), dict(final)
    return [
        {"heading": name, "start": value, "after_words": after_map.get(name), "final": final_map.get(name)}
        for name, value in start
    ]


# ---- Legacy split proposals (versions from before 2026-10-14 may still carry them) ----


def apply_splits(text, proposals, accepted_ids):
    """Apply the accepted split proposals; whitespace inside a paragraph may be normalised."""
    paragraphs = text.split("\n\n")
    for proposal in proposals:
        if proposal["id"] not in accepted_ids:
            continue
        for index, paragraph in enumerate(paragraphs):
            flat = re.sub(r"[ \t]*\n[ \t]*(?![-*#|\d])", " ", paragraph)
            if proposal["original"] in flat:
                paragraphs[index] = flat.replace(proposal["original"], proposal["split"], 1)
                break
    return "\n\n".join(paragraphs)
