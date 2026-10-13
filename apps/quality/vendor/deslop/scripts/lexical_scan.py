#!/usr/bin/env python3
"""Deterministic scan for lexical and formatting tells of LLM-generated prose.

Standard library only. No network. Works on any text or markdown file.

  python lexical_scan.py FILE [--platform=auto|claude|gpt|gemini|perplexity]
                              [--artifacts-only] [--min-severity=low|medium|high]
                              [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2}

# --- authorship artifacts: leaked internal tokens, no innocent explanation ----
ARTIFACTS = {
    "gpt": r"oaicite|contentReference|turn\d+search\d+|turn\d+news\d+",
    "gemini": r"\[cite:\s*\d+\]|\[cite_start\]|\[span_\d+\]|\[span_start\]",
    "grok": r"grok_card|grok_render_citation_card_json",
    "deepseek": r"[【】]",
    "perplexity": r"ppl-ai-file-upload|attached_file|pplx-[a-z0-9]+",
}

# --- density-scored vocabulary --------------------------------------------
VOCAB_HIGH = [
    "delve", "tapestry", "testament", "realm", "multifaceted", "holistic",
    "synergy", "paradigm shift", "game-chang", "cutting-edge", "seamless",
    "ever-evolving", "fast-paced world", "treasure trove", "rich history",
]
VOCAB_MED = [
    "underscore", "underscores", "showcase", "showcases", "foster", "fosters",
    "garner", "garners", "bolster", "bolsters", "pivotal", "crucial", "vital",
    "robust", "meticulous", "intricate", "nuanced", "leverage", "leverages",
    "harness", "harnesses", "unlock", "unlocks", "elevate", "elevates",
    "empower", "empowers", "landscape", "interplay", "enduring", "vibrant",
    "comprehensive", "essential", "streamline", "optimize", "actionable",
    "profound", "invaluable", "myriad", "plethora", "burgeoning",
]

# --- construction patterns -------------------------------------------------
PATTERNS = [
    ("copula-avoidance", "medium",
     r"\b(serves as|serve as|served as|stands as|stand as|functions as|function as|"
     r"acts as|act as|boasts|boast|constitutes|constitute|represents a|represent a)\b",
     "Restore the plain copula: 'is' / 'are'."),

    ("negative-parallelism", "high",
     r"\bnot (?:just|only|merely|simply)\b[^.!?\n]{0,90}?\bbut\b"
     r"|\b(?:isn't|is not|aren't|are not|it's not|its not|wasn't)\b[^.!?\n]{0,70}?\b(?:it's|but|rather)\b"
     r"|\bless (?:a|an|of)\b[^.!?\n]{0,70}?\bthan\b",
     "State the positive claim alone; delete the 'not X' half."),

    ("significance-inflation", "high",
     r"\b(?:stands as a testament|is a testament to|plays? an? (?:crucial|pivotal|vital|key|important|significant) role"
     r"|underscores? the (?:importance|significance|need)|highlights? the (?:importance|significance)"
     r"|reflects? (?:a )?broader|speaks? to the|serves? as a reminder|cannot be overstated)\b",
     "Delete outright. These clauses assert importance instead of demonstrating it."),

    ("participle-tail", "medium",
     r",\s+(?:highlighting|emphasizing|showcasing|underscoring|reflecting|demonstrating|"
     r"ensuring|contributing|fostering|cultivating|allowing|enabling|providing|offering|"
     r"creating|paving the way|making it (?:easier|possible))\b",
     "Drop the tail. It restates the sentence without adding information."),

    ("throat-clearing", "medium",
     r"(?im)^\s*(?:it'?s (?:important|worth) (?:to )?not(?:e|ing)|here'?s the thing|"
     r"the short answer is|let'?s (?:dive|explore|break|take a look)|in conclusion|"
     r"overall,|ultimately,|at its core|when it comes to|in today'?s|in an era)",
     "Delete the opener and start with the claim."),

    ("promotional", "medium",
     r"\b(?:nestled|in the heart of|groundbreaking|revolutionary|world-class|"
     r"state-of-the-art|unparalleled|unrivaled|bustling|breathtaking|must-see)\b",
     "Replace with a specific fact, or cut."),

    ("assistant-opener", "high",
     r"(?im)^\s*(?:certainly|absolutely|great question|sure thing|of course|"
     r"i'?d be happy to|happy to help)[!.,:]",
     "Chat-assistant residue. Delete."),

    ("stock-connective", "low",
     r"(?im)^\s*(?:additionally|furthermore|moreover|that being said|in addition),",
     "Usually deletable; if the link matters, make it specific."),
]

HEDGES = r"\b(?:generally|typically|often|tends? to|somewhat|relatively|fairly|arguably|" \
         r"largely|broadly|usually|in many cases|more or less|to some extent)\b"

INTENSIFIERS = r"\b(?:genuinely|actually|precisely|exactly|squarely|plainly|simply|truly|really)\b"

FENCE_RE = re.compile(r"```.*?```", re.S)
INLINE_RE = re.compile(r"`[^`\n]+`")
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
# Production notes for designers and editors, not published copy.
CUE_RE = re.compile(r"(?m)^\s*\[(?:HERO|VISUAL|SRC|VERIFY)\b[^\]]*\]\s*$")
# Reference apparatus. A Sources or References list is meant to be uniformly
# labelled, so the bold-lead-in and register checks do not apply to it.
APPARATUS_RE = re.compile(
    r"(?ims)^\s*(?:\*\*|#{1,6}\s*)?(?:sources|references|further reading|"
    r"editorial link opportunities)\b.*?(?=^\s*#{1,6}\s|\Z)")
WORD_RE = re.compile(r"\b[\w'’-]+\b")
HEADING_RE = re.compile(r"(?m)^(#{1,6})\s+(.+?)\s*$")
BOLD_RE = re.compile(r"\*\*[^*\n]+\*\*")
BOLD_BULLET_RE = re.compile(r"(?m)^\s*[-*+]\s+\*\*[^*\n]+\*\*")
CURLY_RE = re.compile(r"[‘’“”]")
EMDASH_RE = re.compile(r"—")
BREAK_BEFORE_HEADING_RE = re.compile(r"(?m)^\s*(?:---|\*\*\*|___)\s*$\n+\s*#{1,6}\s")
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def term_to_pattern(term: str):
    """Build a regex for a wordlist term. Returns None for construction-level
    entries containing X/Y placeholders, which no regex can match literally."""
    if re.search(r"\b[XY]\b", term):
        return None
    parts = []
    for tok in term.split():
        if "/" in tok:
            alts = [re.escape(a) for a in tok.split("/") if a]
            parts.append("(?:" + "|".join(alts) + ")")
        else:
            parts.append(re.escape(tok))
    return r"\b" + r"\s+".join(parts) + r"\w*\b"


def load_wordlist(path: Path):
    """Parse a two-class banned-words TSV (term/class/replacement/condition/note).

    Class A = substitute (medium severity). Class B = recast or cut (high).
    Lines starting with # and the header row are ignored.
    """
    out = {"A": [], "B": [], "skipped": []}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        cols = (raw.split("\t") + [""] * 5)[:5]
        term, cls, repl, cond, note = (c.strip() for c in cols)
        if not term or term.lower() == "term":
            continue
        cls = cls.upper()
        if cls not in ("A", "B"):
            continue
        pat = term_to_pattern(term)
        if pat is None:
            out["skipped"].append(term)
            continue
        out[cls].append({"term": term, "pattern": pat, "replacement": repl,
                         "condition": cond, "note": note})
    return out


def mask_code(text: str) -> str:
    """Blank out code spans, preserving offsets so line numbers stay correct."""
    def blank(m: re.Match) -> str:
        return re.sub(r"[^\n]", " ", m.group(0))
    # HTML comments and bracketed production cues are editorial notes, not
    # published copy - they should not count toward word totals or trip the
    # pattern checks. A designer brief is allowed to say "jurisdictions".
    t = APPARATUS_RE.sub(blank, text)
    return INLINE_RE.sub(blank, FENCE_RE.sub(blank,
                         COMMENT_RE.sub(blank, CUE_RE.sub(blank, t))))


def line_index(text: str):
    starts = [0]
    for m in re.finditer(r"\n", text):
        starts.append(m.end())

    def lookup(pos: int) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1
    return lookup


def excerpt(text: str, start: int, end: int, pad: int = 28) -> str:
    a, b = max(0, start - pad), min(len(text), end + pad)
    return re.sub(r"\s+", " ", text[a:b]).strip()


def find_all(prose: str, pattern: str, line_of, cap: int = 8):
    hits = []
    for m in re.finditer(pattern, prose, re.I):
        hits.append({"line": line_of(m.start()),
                     "text": excerpt(prose, m.start(), m.end())})
        if len(hits) >= cap:
            break
    total = sum(1 for _ in re.finditer(pattern, prose, re.I))
    return total, hits


def scan(raw: str, platform: str = "auto", wordlist=None, allow_title_case: bool = False):
    prose = mask_code(raw)
    line_of = line_index(raw)
    words = WORD_RE.findall(prose)
    n_words = max(1, len(words))
    per_k = lambda n: round(n * 1000.0 / n_words, 2)

    findings = []
    detected = []

    # -- artifacts (always reported, any severity filter) --------------------
    for plat, pat in ARTIFACTS.items():
        total, hits = find_all(prose, pat, line_of)
        if total:
            detected.append(plat)
            findings.append({
                "id": "tool-artifact", "severity": "high", "platform": plat,
                "count": total, "per_1k": per_k(total), "examples": hits,
                "fix": f"Leaked {plat} internal token. Delete. This is also broken output.",
            })

    # -- vocabulary density --------------------------------------------------
    if wordlist:
        # External two-class list replaces the built-ins, so a caller sharing a
        # list with another skill has exactly one source of truth.
        for cls, sev, fix in (
            ("B", "high", "Class B: recast the sentence or cut it. No substitute is "
                          "offered because every single-word candidate preserves the "
                          "tic - swapping in an unflagged synonym is the failure mode."),
            ("A", "medium", "Class A: apply the listed replacement. Where the sentence "
                            "survives without the word at all, cut it instead."),
        ):
            for entry in wordlist.get(cls, []):
                total, hits = find_all(prose, entry["pattern"], line_of)
                if not total:
                    continue
                detail = fix
                if entry["replacement"]:
                    detail = f"-> {entry['replacement']}. " + fix
                if entry["condition"]:
                    detail += f"  [only when: {entry['condition']}]"
                if entry["note"]:
                    detail += f"  ({entry['note']})"
                findings.append({
                    "id": f"banned-{cls}:{entry['term']}", "severity": sev,
                    "count": total, "per_1k": per_k(total), "examples": hits,
                    "fix": detail,
                })
        if wordlist.get("skipped"):
            findings.append({
                "id": "wordlist-unscannable", "severity": "low",
                "count": len(wordlist["skipped"]), "per_1k": 0, "examples": [],
                "fix": "Construction-level entries no regex can match literally; "
                       "check by reading: " + ", ".join(wordlist["skipped"][:8]),
            })
    else:
        for label, wl, sev in (("vocab-high", VOCAB_HIGH, "high"),
                               ("vocab-medium", VOCAB_MED, "medium")):
            pat = r"\b(?:" + "|".join(re.escape(w) for w in wl) + r")\w*\b"
            total, hits = find_all(prose, pat, line_of)
            if total:
                findings.append({
                    "id": label, "severity": sev, "count": total,
                    "per_1k": per_k(total), "examples": hits,
                    "fix": "Replace with the plain word, or cut the sentence. Do not "
                           "swap for an unflagged synonym - that preserves the reflex.",
                })

    # -- constructions -------------------------------------------------------
    for pid, sev, pat, fix in PATTERNS:
        total, hits = find_all(prose, pat, line_of)
        if total:
            findings.append({"id": pid, "severity": sev, "count": total,
                             "per_1k": per_k(total), "examples": hits, "fix": fix})

    # -- density-only measures ----------------------------------------------
    for pid, pat, thresh, fix in (
        ("hedge-stacking", HEDGES, 8.0, "Keep at most one hedge per sentence; none on facts."),
        ("intensifier-reflex", INTENSIFIERS, 5.0, "Delete the adverb; the bare verb is stronger."),
    ):
        total, hits = find_all(prose, pat, line_of)
        d = per_k(total)
        if d >= thresh:
            findings.append({"id": pid, "severity": "medium", "count": total,
                             "per_1k": d, "examples": hits, "fix": fix})

    # -- tricolon ------------------------------------------------------------
    tri = r"\b(\w+), (\w+),? and (\w+)\b"
    total, hits = find_all(prose, tri, line_of)
    if per_k(total) >= 3.0:
        findings.append({
            "id": "tricolon", "severity": "low", "count": total, "per_1k": per_k(total),
            "examples": hits,
            "fix": "Check whether the third item is a real claim. Usually it is cadence. "
                   "High false-positive rate - genuine three-item lists trip this.",
        })

    # -- formatting ----------------------------------------------------------
    fmt = {}
    em = len(EMDASH_RE.findall(prose))
    fmt["em_dash_per_1k"] = per_k(em)
    if per_k(em) >= 6.0:
        findings.append({
            "id": "em-dash-overuse", "severity": "medium", "count": em,
            "per_1k": per_k(em), "examples": [],
            "fix": "Convert most to periods. The sentence usually wanted to end.",
        })

    curly = len(CURLY_RE.findall(prose))
    fmt["curly_quotes"] = curly
    if curly:
        findings.append({"id": "curly-quotes", "severity": "low", "count": curly,
                         "per_1k": per_k(curly), "examples": [],
                         "fix": "Smart quotes from an external tool. Convert to straight."})

    headings = HEADING_RE.findall(prose)
    fmt["headings"] = len(headings)
    title_case = 0
    for _, h in headings:
        toks = [t for t in re.findall(r"[A-Za-z][\w'-]*", h) if len(t) > 3]
        if len(toks) >= 3 and sum(1 for t in toks if t[0].isupper()) / len(toks) > 0.8:
            title_case += 1
    fmt["title_case_headings"] = title_case
    if title_case >= 2 and not allow_title_case:
        findings.append({"id": "title-case-headings", "severity": "low", "count": title_case,
                         "per_1k": 0, "examples": [],
                         "fix": "Use sentence case. Pass --allow-title-case if Title Case "
                                "is the publication's house style."})

    bolds = len(BOLD_RE.findall(prose))
    bold_bullets = len(BOLD_BULLET_RE.findall(prose))
    fmt["bold_per_1k"] = per_k(bolds)
    fmt["bold_leadin_bullets"] = bold_bullets
    if bold_bullets >= 5:
        findings.append({
            "id": "bold-leadin-bullets", "severity": "medium", "count": bold_bullets,
            "per_1k": per_k(bold_bullets), "examples": [],
            "fix": "Every bullet identically shaped reads as a glossary. Unbold the ones "
                   "where the bold text is not a real label.",
        })

    brks = len(BREAK_BEFORE_HEADING_RE.findall(prose))
    if brks:
        findings.append({"id": "rule-before-heading", "severity": "low", "count": brks,
                         "per_1k": 0, "examples": [],
                         "fix": "Redundant horizontal rule above a heading."})

    emoji = len(EMOJI_RE.findall(prose))
    fmt["emoji"] = emoji
    if emoji >= 3:
        findings.append({"id": "emoji-as-formatting", "severity": "low", "count": emoji,
                         "per_1k": per_k(emoji), "examples": [],
                         "fix": "Decorative emoji. Remove unless functional."})

    # -- platform inference --------------------------------------------------
    if platform == "auto":
        platform = detected[0] if detected else "claude"

    # -- slop index ----------------------------------------------------------
    weight = {"high": 9.0, "medium": 4.0, "low": 1.5}
    score = 0.0
    for f in findings:
        if f["id"] == "tool-artifact":
            score += 20
        else:
            score += weight[f["severity"]] * min(3.0, 0.5 + f["per_1k"] / 3.0)
    index = int(max(0, min(100, round(score))))

    return {
        "words": n_words,
        "platform": platform,
        "platform_evidence": detected or None,
        "slop_index": index,
        "slop_index_caveat": ("Uncalibrated triage for ranking documents against each "
                              "other. No measured false-positive rate. Not evidence of "
                              "authorship - human writers score high."),
        "formatting": fmt,
        "findings": sorted(findings, key=lambda f: -SEVERITY_ORDER[f["severity"]]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--platform", default="auto",
                    choices=["auto", "claude", "gpt", "gemini", "perplexity"])
    ap.add_argument("--wordlist", metavar="TSV",
                    help="Two-class banned-words TSV (term/class/replacement/"
                         "condition/note). Replaces the built-in vocabulary lists "
                         "so multiple skills can share one source of truth.")
    ap.add_argument("--allow-title-case", action="store_true",
                    help="Suppress the title-case-headings finding. Use when Title Case "
                         "is the publication's house style rather than a tell.")
    ap.add_argument("--artifacts-only", action="store_true")
    ap.add_argument("--min-severity", default="low", choices=["low", "medium", "high"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    p = Path(a.file)
    if not p.is_file():
        print(f"error: not a file: {p}", file=sys.stderr)
        return 2
    raw = p.read_text(encoding="utf-8", errors="replace")

    wl = None
    if a.wordlist:
        wp = Path(a.wordlist)
        if not wp.is_file():
            print(f"error: wordlist not found: {wp}", file=sys.stderr)
            return 2
        wl = load_wordlist(wp)

    res = scan(raw, a.platform, wordlist=wl, allow_title_case=a.allow_title_case)
    if a.artifacts_only:
        res["findings"] = [f for f in res["findings"] if f["id"] == "tool-artifact"]
    else:
        floor = SEVERITY_ORDER[a.min_severity]
        res["findings"] = [f for f in res["findings"]
                           if SEVERITY_ORDER[f["severity"]] >= floor or f["id"] == "tool-artifact"]
    res["file"] = str(p)

    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    print(f"{p}  |  {res['words']} words  |  platform: {res['platform']}"
          f"{' (evidence: ' + ', '.join(res['platform_evidence']) + ')' if res['platform_evidence'] else ' (assumed)'}")
    print(f"slop index: {res['slop_index']}/100   [{res['slop_index_caveat']}]\n")
    if not res["findings"]:
        print("No lexical findings. This does NOT mean the text is fine - "
              "the substantive tier is unchecked.")
        return 0
    for f in res["findings"]:
        print(f"[{f['severity'].upper():6}] {f['id']}  x{f['count']} ({f['per_1k']}/1k words)")
        print(f"          fix: {f['fix']}")
        for ex in f["examples"][:4]:
            print(f"          L{ex['line']}: ...{ex['text']}...")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
