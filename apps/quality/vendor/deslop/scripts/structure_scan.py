#!/usr/bin/env python3
"""Structural rhythm scan: sentence-length variance, paragraph uniformity,
section symmetry, opener repetition, clause complexity.

Standard library only. No network.

  python structure_scan.py FILE [--json]

All bands are heuristic. Report values, not verdicts.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics as st
import sys
from pathlib import Path

FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_RE = re.compile(r"`[^`\n]+`")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TABLE_RE = re.compile(r"(?m)^\s*\|.*$")
CUE_RE = re.compile(r"(?m)^\s*\[(?:HERO|VISUAL|SRC|VERIFY)\b[^\]]*\]\s*$")
WORD_RE = re.compile(r"\b[\w'’-]+\b")
H2_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
MD_NOISE_RE = re.compile(r"(?m)^\s*(?:[-*+]\s+|\d+[.)]\s+|>\s*|#{1,6}\s+|\|)")
SUBORD_RE = re.compile(
    r",\s*(?:which|who|where|when|while|although|though|because|since|whereas|so that)\b"
    r"|\b(?:—|--)\b", re.I)

ABBREVS = ["Mr", "Mrs", "Ms", "Dr", "Prof", "Sr", "Jr", "St", "vs", "etc", "Fig",
           "No", "Inc", "Ltd", "Co", "e.g", "i.e", "cf", "al", "approx"]


def strip_code(text: str) -> str:
    """Remove everything that is not running prose.

    Table rows matter: they carry no sentence-ending punctuation, so an unstripped
    table parses as one enormous sentence and inflates the length variance it is
    supposed to measure. HTML comments are editorial notes, not published copy.
    """
    t = FENCE_RE.sub(" ", text)
    t = INLINE_RE.sub(" ", t)
    t = COMMENT_RE.sub(" ", t)
    t = CUE_RE.sub("", t)
    t = TABLE_RE.sub("", t)
    return t


def sentences(text: str):
    """Split into sentences, protecting known abbreviations and decimals."""
    t = text
    for a in ABBREVS:
        t = re.sub(rf"\b{re.escape(a)}\.", f"{a}\x00", t)
    t = re.sub(r"(\d)\.(\d)", lambda m: m.group(1) + "\x00" + m.group(2), t)
    parts = re.split(r"(?<=[.!?])[\"'’”)\]]*\s+", t)
    out = []
    for s in parts:
        s = s.replace("\x00", ".").strip()
        s = MD_NOISE_RE.sub("", s)
        if len(WORD_RE.findall(s)) >= 2:
            out.append(s)
    return out


SUBORD_OPEN = r"when|if|while|although|though|because|since|after|before|unless|whether|as|once|until|where|given"
PREP_OPEN = r"in|on|at|for|with|by|under|across|through|within|among|behind|beneath|beyond|during|despite|tucked|buried|hidden|written|set|built"
CONJ_OPEN = r"and|but|so|or|yet|nor"
IMPER_OPEN = (r"say|write|ask|take|look|think|imagine|consider|picture|note|remember|try|start|"
              r"put|run|check|read|do|don't|isolate|release|fit|close")


def opener_type(s: str) -> str:
    """Rough grammatical class of a sentence's opening. Heuristic, no POS tagger.

    Length variance says nothing about construction variance: a page of
    subject-first declaratives can have a healthy CV and still march.
    """
    t = s.strip().strip('"“‘')
    if t.endswith("?"):
        return "question"
    first = re.match(r"[A-Za-z']+", t)
    if not first:
        return "other"
    w = first.group(0).lower()
    if re.match(rf"^(?:{CONJ_OPEN})\b", w):
        return "conjunction"
    if re.match(rf"^(?:{SUBORD_OPEN})\b", w):
        return "subordinate"
    if re.match(rf"^(?:{IMPER_OPEN})\b", w):
        return "imperative"
    if re.match(rf"^(?:{PREP_OPEN})\b", w):
        return "prepositional"
    if len(WORD_RE.findall(t)) <= 6 and not re.search(
            r"\b(is|are|was|were|has|have|had|can|will|does|do|did|isn't|aren't)\b", t, re.I):
        return "fragment"
    return "subject-first"


def cv(values):
    if len(values) < 2:
        return 0.0
    m = st.mean(values)
    return round(st.pstdev(values) / m, 3) if m else 0.0


def burstiness_band(v: float) -> str:
    if v < 0.35:
        return "very flat - strong candidate for restructuring"
    if v < 0.50:
        return "flat-ish - weak signal alone, common in edited corporate prose"
    if v <= 0.75:
        return "typical of varied human prose"
    return "highly varied - check it is deliberate, not erratic"


def scan(raw: str):
    text = strip_code(raw)

    sents = sentences(text)
    lens = [len(WORD_RE.findall(s)) for s in sents]
    n_words = sum(lens)

    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if len(WORD_RE.findall(p)) >= 15]
    para_lens = [len(WORD_RE.findall(p)) for p in paras]

    findings = []

    # -- sentence rhythm -----------------------------------------------------
    s_cv = cv(lens)
    midband = round(sum(1 for L in lens if 12 <= L <= 25) / len(lens), 3) if lens else 0.0
    if lens and s_cv < 0.40:
        findings.append({
            "id": "flat-sentence-rhythm", "severity": "high" if s_cv < 0.33 else "medium",
            "value": s_cv,
            "fix": "Let length follow content - some ideas need a clause, some a paragraph. "
                   "Do NOT inject short sentences on a schedule; forced variance is a "
                   "rarer fingerprint than flat variance.",
        })
    if midband > 0.65:
        findings.append({
            "id": "mid-band-concentration", "severity": "medium", "value": midband,
            "fix": f"{int(midband*100)}% of sentences are 12-25 words. Most sentences are "
                   "the same size regardless of what the CV says.",
        })

    # -- paragraph uniformity ------------------------------------------------
    p_cv = cv(para_lens)
    if len(para_lens) >= 8 and p_cv < 0.30:
        findings.append({
            "id": "uniform-paragraphs", "severity": "medium", "value": p_cv,
            "fix": "Paragraphs are near-identical in length, which suggests filling a "
                   "shape rather than following an argument.",
        })

    # -- section symmetry ----------------------------------------------------
    sec_words, sections = [], H2_RE.split(text)
    if len(sections) > 2:
        for body in sections[2::2]:
            sec_words.append(len(WORD_RE.findall(body)))
    sec_cv = cv(sec_words)
    if len(sec_words) >= 3 and sec_cv < 0.25:
        findings.append({
            "id": "symmetric-sections", "severity": "low", "value": sec_cv,
            "fix": "Sections are near-equal in length. Real documents are lopsided - the "
                   "section the author cared about is longer.",
        })

    # -- opener repetition ---------------------------------------------------
    openers, ratio = [], 1.0
    for p in paras:
        w = WORD_RE.findall(p)
        if len(w) >= 2:
            openers.append((w[0].lower(), w[1].lower()))
    if openers:
        ratio = round(len(set(openers)) / len(openers), 3)
        if ratio < 0.70:
            common = {}
            for o in openers:
                common[o] = common.get(o, 0) + 1
            top = sorted(common.items(), key=lambda kv: -kv[1])[:4]
            findings.append({
                "id": "repeated-openers", "severity": "medium", "value": ratio,
                "fix": "Paragraphs start the same way. Most repeated: "
                       + ", ".join(f"'{' '.join(k)}' x{v}" for k, v in top),
            })

    # -- opener construction variety ----------------------------------------
    op_counts = {}
    for s in sents:
        op_counts[opener_type(s)] = op_counts.get(opener_type(s), 0) + 1
    subj_share = round(op_counts.get("subject-first", 0) / len(sents), 3) if sents else 0.0
    # 0.65 was a guess; recalibrated against an approved sample that sits at 0.69
    # and reads well. Flag only genuine monotony.
    if subj_share > 0.80:
        findings.append({
            "id": "uniform-sentence-construction", "severity": "high",
            "value": subj_share,
            "fix": f"{int(subj_share*100)}% of sentences open subject-first. Length variance "
                   "cannot see this - a page of subject-verb-object declaratives scores a "
                   "healthy CV and still marches. Vary the build, not just the length: open "
                   "some on a subordinate clause, let some turn mid-sentence on a comma or "
                   "semicolon, use a conditional or imperative opener where it fits.",
        })

    # -- clause complexity (weight this for Claude-authored text) -----------
    subord = sum(1 for s in sents if SUBORD_RE.search(s))
    sub_ratio = round(subord / len(sents), 3) if sents else 0.0
    if sub_ratio > 0.45:
        findings.append({
            "id": "high-subordinate-clause-ratio", "severity": "medium", "value": sub_ratio,
            "fix": "Most sentences carry a subordinate clause or dash aside. This is the "
                   "rhythm tell that survives when sentence-length variance looks fine - "
                   "weight it heavily for Claude-authored text.",
        })

    longest = max(lens) if lens else 0
    shortest = min(lens) if lens else 0

    return {
        "words": n_words,
        "sentences": len(sents),
        "paragraphs": len(paras),
        "sentence_len_mean": round(st.mean(lens), 2) if lens else 0,
        "sentence_len_cv": s_cv,
        "sentence_len_band": burstiness_band(s_cv),
        "sentence_len_min": shortest,
        "sentence_len_max": longest,
        "mid_band_fraction": midband,
        "paragraph_len_cv": p_cv,
        "section_len_cv": sec_cv,
        "section_count": len(sec_words),
        "opener_diversity": ratio,
        "subject_first_share": subj_share,
        "opener_types": op_counts,
        "subordinate_clause_ratio": sub_ratio,
        "caveat": "Heuristic bands with no measured false-positive rate. Technical and "
                  "legal writing is legitimately uniform. Values, not verdicts.",
        "findings": findings,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    p = Path(a.file)
    if not p.is_file():
        print(f"error: not a file: {p}", file=sys.stderr)
        return 2
    res = scan(p.read_text(encoding="utf-8", errors="replace"))
    res["file"] = str(p)

    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    print(f"{p}  |  {res['words']} words, {res['sentences']} sentences, "
          f"{res['paragraphs']} paragraphs\n")
    print(f"  sentence length   mean {res['sentence_len_mean']}  "
          f"range {res['sentence_len_min']}-{res['sentence_len_max']}")
    print(f"  burstiness (CV)   {res['sentence_len_cv']}  -> {res['sentence_len_band']}")
    print(f"  mid-band 12-25w   {int(res['mid_band_fraction']*100)}%")
    print(f"  paragraph CV      {res['paragraph_len_cv']}")
    print(f"  section CV        {res['section_len_cv']} across {res['section_count']} sections")
    print(f"  opener diversity  {res['opener_diversity']}")
    print(f"  subject-first     {res['subject_first_share']}  "
          + " ".join(f"{k}:{v}" for k, v in sorted(res["opener_types"].items(),
                                                   key=lambda kv: -kv[1])))
    print(f"  subord. clauses   {res['subordinate_clause_ratio']}\n")
    for f in res["findings"]:
        print(f"[{f['severity'].upper():6}] {f['id']} = {f['value']}")
        print(f"          fix: {f['fix']}\n")
    if not res["findings"]:
        print("No structural findings. The substantive tier is still unchecked.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
