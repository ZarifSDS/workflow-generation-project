#!/usr/bin/env python3
"""
frame_scan.py - countable subset of the clarity-review checklist.

Produces CANDIDATES for a human read, never verdicts. Every hit below is a
legal construction; the defect is contextual (does the referent resolve? is the
frame repeated past the point of being a tic?). Nothing here can decide that.

Covers checklist items that are genuinely countable:
  5. repeated syntactic frames  (cleft/emphasis constructions, counted)
  1. unresolved referent        (bare demonstratives + placeholder nouns, candidates)
  3. term drift                 (--terms, counted)
  4. person/voice break         (mixed-person paragraphs, rough heuristic)

Does NOT cover, because it needs comprehension: audience-mismatched jargon,
register drift, metaphor-for-plain-word, idiom collision, circular definition.
Read for those.

Markdown-aware: skips fenced code, tables, headings, and link URLs.
Stdlib only.

Usage:
  python frame_scan.py FILE
  python frame_scan.py FILE --terms "program,system,platform"
  python frame_scan.py FILE --json
  python frame_scan.py FILE --frame-threshold 3
"""

import sys, os, re, json, argparse

# ---------------------------------------------------------------- text extraction

def prose_lines(raw):
    """Yield (lineno, text) for prose lines only: no code fences, tables, headings."""
    out, in_fence = [], False
    for i, line in enumerate(raw.split("\n"), 1):
        s = line.strip()
        if s.startswith("```") or s.startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence or not s:
            continue
        if s.startswith("#") or s.startswith("|") or s.startswith(">"):
            continue
        out.append((i, line))
    return out


def strip_markup(text):
    """Link text kept, URLs dropped; emphasis and inline code removed."""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"[*_]{1,3}", "", text)
    text = re.sub(r"^\s*(?:[-*+]|\d+\.)\s+", "", text)
    return text


def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [p.strip() for p in parts if len(p.split()) > 1]


# ---------------------------------------------------------------- item 5: frames

# Each frame: (id, human label, compiled regex). Deliberately narrow - these are
# specific constructions, not general grammar.
FRAMES = [
    ("cleft-is-what",
     "X is/are what Y  (cleft; converts to plain subject-verb)",
     re.compile(r"\b(?:is|are|was|were)\s+what\s+\w+", re.I)),
    ("cleft-what-is",
     "What X is/does Y  (fronted wh-cleft)",
     re.compile(r"(?:^|(?<=[.;:]\s))\s*What\s+[^.;:!?]{3,60}?\s+(?:is|are|was|were|does|do)\b", re.I)),
    ("cleft-it-is-that",
     "It is X that Y  (it-cleft)",
     re.compile(r"\bIt\s+(?:is|was)\s+[^.;:!?]{2,50}?\s+that\b", re.I)),
    ("existential-there",
     "There is/are X that Y",
     re.compile(r"\bThere\s+(?:is|are|was|were)\s+\w+", re.I)),
    # Negative lookbehinds keep this from double-reporting sentences already
    # counted by cleft-is-what above.
    ("what-makes",
     "what makes/keeps/prevents X  (not already counted as a cleft)",
     re.compile(r"(?<!is )(?<!are )(?<!was )(?<!were )"
                r"\bwhat\s+(?:makes|keeps|prevents|stops|drives|causes)\b", re.I)),
    ("the-thing-is",
     "The X here/itself is ...  (emphasis frame)",
     re.compile(r"\bThe\s+\w+\s+(?:here|itself|though)\s+(?:is|was)\b", re.I)),
]


def scan_frames(items, threshold):
    hits = {fid: [] for fid, _, _ in FRAMES}
    for lineno, text in items:
        clean = strip_markup(text)
        for sent in sentences(clean):
            for fid, _, rx in FRAMES:
                m = rx.search(sent)
                if m:
                    hits[fid].append({"line": lineno, "match": m.group(0).strip(),
                                      "sentence": sent[:150]})
    findings = []
    for fid, label, _ in FRAMES:
        h = hits[fid]
        if len(h) >= threshold:
            findings.append({"id": fid, "label": label, "count": len(h),
                             "instances": h})
    return findings, {fid: len(hits[fid]) for fid, _, _ in FRAMES}


# ---------------------------------------------------------------- item 1: referents

# Sentence-initial demonstrative followed directly by a verb = bare demonstrative
# with no restating noun. "This keeps..." (bare) vs "This system keeps..." (fine).
BARE_DEM = re.compile(
    r"(?:^|(?<=[.;:]\s))\s*(This|That|These|Those|It)\s+"
    r"(?=(?:is|are|was|were|means|keeps|makes|prevents|works|matters|happens|"
    r"comes|gives|shows|leaves|creates|becomes|reads|holds|takes|helps|"
    r"can|will|would|should|does|do|did)\b)", re.I)

PLACEHOLDER = re.compile(
    r"\b(something|someone|somebody|anything|things|stuff|aspects?|elements?|"
    r"areas?|factors?|items?|the work|the process|the results?|the standard)\b", re.I)

ORPHAN_POSS = re.compile(r"\b(yours|theirs|ours|hers)\b", re.I)


def scan_referents(items):
    bare, place, orphan = [], [], []
    for lineno, text in items:
        clean = strip_markup(text)
        for sent in sentences(clean):
            m = BARE_DEM.search(sent)
            if m:
                bare.append({"line": lineno, "match": m.group(1),
                             "sentence": sent[:150]})
            for m in PLACEHOLDER.finditer(sent):
                place.append({"line": lineno, "match": m.group(0),
                              "sentence": sent[:150]})
            for m in ORPHAN_POSS.finditer(sent):
                orphan.append({"line": lineno, "match": m.group(0),
                               "sentence": sent[:150]})
    return bare, place, orphan


# ---------------------------------------------------------------- item 3: term drift

def scan_terms(items, terms):
    counts = {t: [] for t in terms}
    for lineno, text in items:
        clean = strip_markup(text)
        for t in terms:
            for m in re.finditer(r"\b" + re.escape(t) + r"s?\b", clean, re.I):
                counts[t].append({"line": lineno, "match": m.group(0)})
    return counts


# ---------------------------------------------------------------- item 4: person mix

IMPERATIVE_STARTERS = {
    "offer", "confirm", "tag", "attach", "schedule", "pilot", "start", "fix",
    "standardize", "put", "spend", "write", "keep", "lock", "check", "use",
    "run", "make", "treat", "read", "cut", "add", "flag", "pick", "send",
    "give", "take", "move", "note", "avoid", "review", "count", "name",
}
THIRD_PERSON = re.compile(
    # pronoun or article+noun followed by a finite verb: either an explicit
    # auxiliary/common verb, or any present-tense third-person -s form
    r"\b(?:it|he|she|they|the\s+\w+|an?\s+\w+)\s+"
    r"(?:is|are|was|were|has|have|had|does|do|did|can|will|would|\w+s)\b", re.I)
SECOND_PERSON = re.compile(r"\b(?:you|your|yours)\b", re.I)


def scan_person(raw):
    """Flag paragraphs mixing a bare imperative with third-person narration."""
    out = []
    blocks = re.split(r"\n\s*\n", raw)
    lineno = 1
    for block in blocks:
        nlines = block.count("\n") + 1
        s = block.strip()
        if s and not s.startswith(("#", "|", "```", ">")):
            clean = strip_markup(s)
            sents = sentences(clean)
            imps, thirds = [], []
            for sent in sents:
                first = re.match(r"\s*([A-Za-z]+)", sent)
                if first and first.group(1).lower() in IMPERATIVE_STARTERS:
                    if not SECOND_PERSON.search(sent):
                        imps.append(sent[:110])
                if THIRD_PERSON.search(sent):
                    thirds.append(sent[:110])
            if imps and thirds and len(sents) > 1:
                out.append({"line": lineno, "imperative": imps[0],
                            "third_person": thirds[0]})
        lineno += nlines + 1
    return out


# ---------------------------------------------------------------- report

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--terms", default="",
                    help="Comma-separated concept terms to check for drift, "
                         "e.g. \"program,system,platform\"")
    ap.add_argument("--frame-threshold", type=int, default=4,
                    help="Report a syntactic frame at or above this count (default 4)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if not os.path.exists(a.file):
        print("no such file: %s" % a.file, file=sys.stderr)
        return 2
    raw = open(a.file, encoding="utf-8").read()
    items = prose_lines(raw)
    words = len(re.findall(r"[A-Za-z0-9'-]+", strip_markup(" ".join(t for _, t in items))))

    frames, frame_counts = scan_frames(items, a.frame_threshold)
    bare, place, orphan = scan_referents(items)
    person = scan_person(raw)
    terms = [t.strip() for t in a.terms.split(",") if t.strip()]
    term_counts = scan_terms(items, terms) if terms else {}

    result = {
        "file": a.file, "prose_words": words,
        "frames_over_threshold": frames,
        "frame_counts_all": frame_counts,
        "bare_demonstratives": bare,
        "placeholder_nouns": place,
        "orphan_possessives": orphan,
        "mixed_person_paragraphs": person,
        "term_drift": {k: len(v) for k, v in term_counts.items()},
        "note": ("Candidates for a human read, not defects. Bare demonstratives and "
                 "placeholder nouns are legal English; the question is whether the "
                 "referent resolves for the reader. Audience-mismatched jargon, "
                 "register drift, metaphor-for-plain-word, idiom collision and "
                 "circular definition are NOT covered here - read for those."),
    }

    if a.json:
        print(json.dumps(result, indent=2))
        return 0

    print("CLARITY FRAME SCAN: %s" % a.file)
    print("  %d prose words\n" % words)

    print("== Item 5: repeated syntactic frames (threshold %d) ==" % a.frame_threshold)
    if frames:
        for f in frames:
            print("  [%d x] %s" % (f["count"], f["label"]))
            for ins in f["instances"][:6]:
                print("      L%-4s %s" % (ins["line"], ins["match"]))
            if len(f["instances"]) > 6:
                print("      ... and %d more" % (len(f["instances"]) - 6))
        print("  -> convert most to plain subject-verb; keep at most one for emphasis")
    else:
        print("  none at or above threshold")
    sub = {k: v for k, v in frame_counts.items() if v}
    if sub:
        print("  all frame counts: %s" % ", ".join("%s=%d" % kv for kv in sorted(sub.items())))

    print("\n== Item 1: referent candidates (read each; is the antecedent findable?) ==")
    if bare:
        print("  bare demonstratives (%d):" % len(bare))
        for h in bare[:8]:
            print("      L%-4s \"%s ...\"  %s" % (h["line"], h["match"], h["sentence"][:90]))
        if len(bare) > 8:
            print("      ... and %d more" % (len(bare) - 8))
    if place:
        print("  placeholder nouns (%d):" % len(place))
        seen = {}
        for h in place:
            seen.setdefault(h["match"].lower(), []).append(h["line"])
        for k, v in sorted(seen.items(), key=lambda x: -len(x[1])):
            print("      %-16s x%d  (lines %s)" % (k, len(v), ", ".join(str(n) for n in v[:6])))
    if orphan:
        print("  orphan possessives (%d):" % len(orphan))
        for h in orphan[:6]:
            print("      L%-4s \"%s\"  %s" % (h["line"], h["match"], h["sentence"][:90]))
    if not (bare or place or orphan):
        print("  no candidates")

    print("\n== Item 4: mixed-person paragraphs (rough heuristic) ==")
    if person:
        for p in person:
            print("  L%-4s imperative: %s" % (p["line"], p["imperative"]))
            print("        third-person: %s" % p["third_person"])
        print("  -> put both sentences in the same grammatical person")
    else:
        print("  none detected")

    if term_counts:
        print("\n== Item 3: term drift ==")
        nz = {k: len(v) for k, v in term_counts.items() if v}
        for k, n in sorted(nz.items(), key=lambda x: -x[1]):
            print("  %-20s x%d" % (k, n))
        if len(nz) > 1:
            print("  -> %d of these terms appear; confirm they name DIFFERENT concepts,"
                  % len(nz))
            print("     not one concept under rotating names")

    print("\n" + "-" * 66)
    print("Candidates, not defects. Not covered here (read for these):")
    print("  item 2 audience-mismatched jargon   item 6 register drift")
    print("  item 7 metaphor for a plain word    item 8 idiom collision")
    print("  item 9 one-sided comparison         item 10 circular definition")
    return 0


if __name__ == "__main__":
    sys.exit(main())
