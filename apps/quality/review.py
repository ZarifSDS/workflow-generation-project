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

MARKER = re.compile(r"\[(?:VERIFY|SRC:[^\]]*|VISUAL:[^\]]*|HERO:[^\]]*)\]")
NEGATION = re.compile(
    r"\b(?:no|not|never|none|nor|cannot|without|can't|don't|doesn't|isn't|aren't|won't|wasn't|weren't|"
    r"shouldn't|mustn't|didn't|hasn't|haven't)\b",
    re.I,
)
UNFOLDABLE_NEGATION = re.compile(r"\bnot (?:just|only|merely)\b|\bnot\b[^.!?\n]{0,80}?\bbut\b", re.I)


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


def grade(text):
    return scripts.fkgl(prose(text))


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
    sentences = m.split_sentences(m.strip_markdown(prose(article_text(text))))
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


def protected_spans(text):
    """Things a rewrite must never change: numbers with what they count, section and regulation
    references, URLs, acronyms (agencies, statutes) and markers."""
    flat = re.sub(r"\s+", " ", text)
    spans = set(
        re.findall(r"\d+(?:[.,:/-]\d+)*(?:\([a-z0-9]+\))*(?:\s?%| (?!the\b|and\b|or\b|of\b)[A-Za-z]+)?", flat)
    )
    spans |= set(
        re.findall(
            r"\b(?:Section|Regulation|Part|Article|Schedule|Rule|Subpart|Appendix)\s+[\dA-Z][\w.()-]*", flat
        )
    )
    spans |= set(re.findall(r"(?:https?|wagtail)://[^\s)\]]+", flat))
    spans |= set(re.findall(r"\b[A-Z]{2,}[A-Z0-9&]*\b", flat))
    spans |= set(MARKER.findall(flat))
    return spans


def protected_ok(before, after):
    """(ok, reason): every protected span survives, and no negation is lost (unfolding a 'not X but Y'
    into the positive claim may remove its 'not')."""
    missing = sorted(protected_spans(before) - protected_spans(after))
    if missing:
        shown = ", ".join(f"“{span}”" for span in missing[:5])
        return False, f"it changed or dropped protected facts: {shown}"
    lost = len(NEGATION.findall(before)) - len(NEGATION.findall(after))
    # Only an unfoldable "not X but Y" that actually disappeared may account for a lost negation.
    unfolded = len(UNFOLDABLE_NEGATION.findall(before)) - len(UNFOLDABLE_NEGATION.findall(after))
    if lost > max(unfolded, 0):
        return False, "it dropped a negation (no, not, never…), which can reverse a claim"
    return True, ""


def accept_rewrite(before, after, min_ratio=0.75):
    """A rewrite is kept only if it keeps every heading, most of the words and every protected fact."""
    after = (after or "").strip()
    if not after:
        return False, "empty output"
    if len(_headings(after)) < len(_headings(before)):
        return False, "headings were dropped"
    if len(after.split()) < min_ratio * len(before.split()):
        return False, "too much text was removed"
    return protected_ok(before, after)


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
    edited = (
        call("review_wordlevel", {"section": original, "grade": before, "target": target, "region": region})
        or ""
    ).strip()
    if heading and not edited.startswith("#"):
        edited = f"{heading.strip()}\n\n{edited}"
    ok, reason = accept_rewrite(original, edited, min_ratio=0.8)
    if not ok:
        raise ValueError(f"The rewrite wasn't used ({reason}).")
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
        f"{len(findings)} scanner finding(s) addressed with the deslop rewrite rules.",
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
    findings = []
    for finding in lexical.get("findings") or []:
        examples = "; ".join(e.get("text", "").strip() for e in (finding.get("examples") or [])[:4])
        findings.append(
            f"- {finding.get('id')} ({finding.get('severity')}, {finding.get('count')}×): {examples}"
        )
    for finding in (structure.get("findings") or [])[:6]:
        findings.append(f"- structure: {finding.get('id', '')} {finding.get('message', '') or finding}"[:240])
    for finding in (redundancy.get("findings") or [])[:6]:
        findings.append(f"- repeated across sections: {str(finding)[:200]}")
    return findings


def _clarity_candidates(frames):
    candidates = []
    for item in (frames.get("bare_demonstratives") or [])[:12]:
        candidates.append(f"- unclear reference “{item.get('match')}”: {item.get('sentence', '')[:200]}")
    for item in (frames.get("placeholder_nouns") or [])[:8]:
        candidates.append(f"- vague noun “{item.get('match')}”: {item.get('sentence', '')[:200]}")
    for item in (frames.get("frames_over_threshold") or [])[:6]:
        candidates.append(f"- repeated sentence frame: {str(item)[:200]}")
    for item in (frames.get("term_variants") or frames.get("terms") or [])[:6]:
        candidates.append(f"- possible term drift: {str(item)[:200]}")
    for item in (frames.get("mixed_person_paragraphs") or [])[:4]:
        candidates.append(f"- mixed person in one paragraph near line {item.get('line')}")
    return candidates


def _rewrite_pass(result, call, number, name, prompt, context, notes_heading, summary):
    before = result.text
    reply = call(prompt, {"article": before, **context}) or ""
    after, notes = split_notes(reply, notes_heading)
    if notes_heading == "Deslop notes":
        result.questions = notes
    else:
        result.clarity_edits = notes
    ok, reason = accept_rewrite(before, after)
    if ok:
        result.text = after.strip() + "\n"
        detail = f" {len(notes)} note(s)." if notes else ""
        _record(result, number, name, after.strip() != before.strip(), summary + detail, notes=notes)
    else:
        _record(
            result, number, name, False, f"Rewrite not used ({reason}); text left unchanged.", notes=notes
        )


def _auto_tune(result, call, brief, target):
    order = sorted(
        (
            (value, name)
            for name, value in section_grades(result.text)
            if value and value > target + TUNE_TOLERANCE
        ),
        reverse=True,
    )
    changed, skipped = [], []
    for _, name in order[:MAX_TUNED_SECTIONS]:
        names = [heading_name(h) for h, _ in section_units(result.text)]
        if name not in names:
            continue
        try:
            result.text, before, after = tune_unit(
                result.text, names.index(name), target, brief.get("region", ""), call
            )
            changed.append(f"{name}: {before} → {after}")
        except ValueError as error:
            skipped.append(f"{name}: {error}")
    summary = "; ".join(changed) if changed else f"No section more than {TUNE_TOLERANCE:g} above the target."
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
