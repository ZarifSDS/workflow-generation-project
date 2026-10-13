"""The review-and-edit sequence (docs/workflow.md):

1 grade scan per section → 2 de-slop → 3 clarity → 4 strip meta narration → 5 word-level edits in
sections above grade 13 → 6 re-scan → 7 propose targeted sentence splits (never applied automatically).

`call(prompt_name, context) -> str` is injected, so the sequence runs with any model and in tests.
"""

import json
import re
import uuid
from dataclasses import dataclass, field

from . import scripts

HIGH_GRADE = 13.0
SPLIT_MIN_GAIN = 1.0  # a split must lower its section's grade by at least this much
SPLIT_CANDIDATE_WORDS = 22
META_PATTERNS = [
    r"\bin this (article|post|guide|blog)\b",
    r"\blet'?s (dive|explore|take a (closer )?look)\b",
    r"\bas (mentioned|discussed|noted) (above|earlier|previously)\b",
    r"\bwe will (explore|discuss|cover|look at)\b",
    r"\bwithout further ado\b",
    r"\bin conclusion\b",
    r"\bthis (article|guide) (will|covers|explains)\b",
]


@dataclass
class ReviewResult:
    text: str
    substeps: list = field(default_factory=list)
    grades: list = field(default_factory=list)  # [{heading, start, after_words, final}]
    proposals: list = field(default_factory=list)  # split proposals


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


def section_grades(text):
    return [(heading_name(h), scripts.fkgl(h + b)) for h, b in split_sections(text)]


def _headings(text):
    return re.findall(r"(?m)^#{1,3}\s+.+$", text)


def _accept_rewrite(before, after, min_ratio=0.75):
    """A rewrite is kept only if it keeps every heading and most of the words."""
    after = (after or "").strip()
    if not after:
        return False, "empty output"
    if len(_headings(after)) < len(_headings(before)):
        return False, "headings were dropped"
    if len(after.split()) < min_ratio * len(before.split()):
        return False, "too much text was removed"
    return True, ""


def _record(result, number, name, changed, summary, **extra):
    result.substeps.append({"number": number, "name": name, "changed": changed, "summary": summary, **extra})


# ---- Sequence ----


def run_sequence(text, brief, call):
    target = float(brief.get("fkgl") or 9)
    result = ReviewResult(text=text.strip() + "\n")
    start = section_grades(result.text)
    high = [name for name, grade in start if grade and grade > HIGH_GRADE]
    _record(
        result,
        1,
        "Grade scan",
        False,
        f"{len(start)} sections measured; {len(high)} above grade {HIGH_GRADE:g}.",
    )

    _deslop(result, call)
    _clarity(result, call)
    _meta(result, call)
    after_words = _word_level(result, call, brief)

    final = section_grades(result.text)
    still_high = [name for name, grade in final if grade and grade > target + 1]
    _record(
        result,
        6,
        "Re-scan",
        False,
        f"{len(still_high)} section(s) still more than a grade above target {target:g}.",
    )
    _propose_splits(result, call, target)

    result.grades = _grade_rows(start, after_words, final)
    return result


def _grade_rows(start, after_words, final):
    """Line up grades per section. Rewrites can reword headings, so match by position when the
    number of sections is unchanged, otherwise by heading text."""
    if len(start) == len(after_words) == len(final):
        return [
            {
                "heading": final[i][0],
                "start": start[i][1],
                "after_words": after_words[i][1],
                "final": final[i][1],
            }
            for i in range(len(start))
        ]
    after_map, final_map = dict(after_words), dict(final)
    return [
        {"heading": name, "start": grade, "after_words": after_map.get(name), "final": final_map.get(name)}
        for name, grade in start
    ]


def _deslop(result, call):
    lexical = _scan("lexical", result.text) or {}
    redundancy = _scan("redundancy", result.text) or {}
    findings = []
    for finding in lexical.get("findings", []):
        examples = "; ".join(e.get("text", "").strip() for e in (finding.get("examples") or [])[:4])
        findings.append(
            f"- {finding.get('id')} ({finding.get('severity')}, {finding.get('count')}×): {examples}"
        )
    for finding in redundancy.get("findings", [])[:6]:
        findings.append(f"- repeated phrase: {json.dumps(finding)[:200]}")
    if not findings:
        _record(result, 2, "De-slop", False, "No AI-tell findings.", slop_index=lexical.get("slop_index"))
        return
    _rewrite(
        result,
        call,
        2,
        "De-slop",
        "review_deslop",
        {"findings": "\n".join(findings)},
        f"{len(findings)} finding(s) addressed.",
        slop_before=lexical.get("slop_index"),
    )


def _clarity(result, call):
    frames = _scan("frames", result.text) or {}
    candidates = []
    for item in (frames.get("bare_demonstratives") or [])[:12]:
        candidates.append(f"- unclear reference “{item.get('match')}”: {item.get('sentence', '')[:200]}")
    for item in (frames.get("placeholder_nouns") or [])[:8]:
        candidates.append(f"- vague noun “{item.get('match')}”: {item.get('sentence', '')[:200]}")
    for item in (frames.get("frames_over_threshold") or [])[:6]:
        candidates.append(f"- repeated sentence frame: {json.dumps(item)[:200]}")
    for item in (frames.get("mixed_person_paragraphs") or [])[:4]:
        candidates.append(f"- mixed person in one paragraph near line {item.get('line')}")
    if not candidates:
        _record(result, 3, "Clarity review", False, "No clarity candidates.")
        return
    _rewrite(
        result,
        call,
        3,
        "Clarity review",
        "review_clarity",
        {"candidates": "\n".join(candidates)},
        f"{len(candidates)} candidate(s) reviewed.",
    )


def _meta(result, call):
    sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", result.text))
    found = [s for s in sentences if any(re.search(p, s, re.I) for p in META_PATTERNS)]
    if not found:
        _record(result, 4, "Strip meta narration", False, "No meta narration found.")
        return
    listing = "\n".join(f"- {s[:240]}" for s in found[:12])
    _rewrite(
        result,
        call,
        4,
        "Strip meta narration",
        "review_meta",
        {"sentences": listing},
        f"{len(found)} sentence(s) of meta narration removed or rewritten.",
    )


def _word_level(result, call, brief):
    sections = split_sections(result.text)
    changed, grades_after = [], []
    for index, (heading, body) in enumerate(sections):
        name, grade = heading_name(heading), scripts.fkgl(heading + body)
        if not grade or grade <= HIGH_GRADE:
            grades_after.append((name, grade))
            continue
        original = (heading + body).strip()
        edited = (
            call(
                "review_wordlevel",
                {
                    "section": original,
                    "grade": grade,
                    "target": brief.get("fkgl"),
                    "region": brief.get("region", ""),
                },
            )
            or ""
        ).strip()
        if heading and not edited.startswith("##"):
            edited = f"{heading.strip()}\n\n{edited}"  # keep the section's heading
        ok, _reason = _accept_rewrite(original, edited, min_ratio=0.85)
        if ok:
            sections[index] = ("", edited + "\n\n")  # re-split later; heading is inside the text
            new_grade = scripts.fkgl(edited)
            changed.append(f"{name}: {grade} → {new_grade}")
            grades_after.append((name, new_grade))
        else:
            grades_after.append((name, grade))
    result.text = join_sections(sections).strip() + "\n"
    summary = "; ".join(changed) if changed else "No section above grade 13."
    _record(result, 5, "Word-level edits (above grade 13)", bool(changed), summary)
    return grades_after


def _propose_splits(result, call, target):
    candidates = []
    for heading, body in split_sections(result.text):
        grade = scripts.fkgl(heading + body)
        if not grade or grade <= target + 1:
            continue
        sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", body).strip())
        long = sorted(
            (s for s in sentences if len(s.split()) >= SPLIT_CANDIDATE_WORDS), key=len, reverse=True
        )
        candidates += [(heading, s) for s in long[:4]]
    if not candidates:
        _record(result, 7, "Targeted splits", False, "No section needs splits.")
        return
    reply = call(
        "review_splits", {"sentences": "\n".join(f"{i + 1}. {s}" for i, (_, s) in enumerate(candidates))}
    )
    for item in _parse_json_list(reply):
        number, split = item.get("n"), (item.get("split") or "").strip()
        if not isinstance(number, int) or not 1 <= number <= len(candidates) or not split:
            continue
        heading, original = candidates[number - 1]
        section = next(h + b for h, b in split_sections(result.text) if h == heading)
        before = scripts.fkgl(section)
        after = scripts.fkgl(_replace_sentence(section, original, split))
        if before is not None and after is not None and before - after >= SPLIT_MIN_GAIN:
            result.proposals.append(
                {
                    "id": uuid.uuid4().hex[:8],
                    "section": heading_name(heading),
                    "original": original,
                    "split": split,
                    "before": before,
                    "after": after,
                }
            )
    _record(
        result,
        7,
        "Targeted splits",
        False,
        f"{len(result.proposals)} split(s) proposed (each lowers its section by ≥ {SPLIT_MIN_GAIN:g} grade).",
    )


# ---- Helpers ----


def _scan(name, text):
    try:
        return scripts.run_json(name, text)
    except (scripts.ScriptError, OSError):
        return None


def _rewrite(result, call, number, name, prompt, context, summary, **extra):
    before = result.text
    after = call(prompt, {"article": before, **context})
    ok, reason = _accept_rewrite(before, after)
    if ok:
        result.text = after.strip() + "\n"
        _record(result, number, name, True, summary, **extra)
    else:
        _record(result, number, name, False, f"Rewrite not used ({reason}); text left unchanged.", **extra)


def _replace_sentence(text, original, replacement):
    flat = re.sub(r"\s+", " ", text)
    return flat.replace(original, replacement, 1) if original in flat else text


def _parse_json_list(reply):
    match = re.search(r"\[.*\]", reply or "", re.S)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return [item for item in data if isinstance(item, dict)]


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
