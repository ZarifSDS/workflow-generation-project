#!/usr/bin/env python3
"""
mechanical_sweep.py - deterministic Step 3A / de-AI mechanical checks.

Flags the sweeps that are pure string work: em/en dashes, curly quotes and
apostrophes, emoji, thematic-break separators, likely title-case headings,
over-use of "key" as an adjective, banned-word occurrences (from the
single-source data/banned-words.json), invisible/format Unicode carriers,
Docs round-trip spacing and escape artifacts, and leaked [VERIFY]/[SRC:]
markers.

Stdlib only. Usage:
    python3 mechanical_sweep.py DRAFT.md [--json] [--banned PATH] [--no-gate]

The banned-words file defaults to ../data/banned-words.json relative to this
script, so it resolves whether the active skill is ehs-seo-blog or
ehs-seo-blog-optimized. Pass --banned to override.

This reports; it does not rewrite. Judgment fixes stay with the model.

EXIT CODE: 1 when the BLOCKING set is non-empty, else 0. The blocking set is
em/en dashes, curly quotes, emoji, thematic breaks, escaped punctuation,
spacing defects, invisible Unicode, and surviving [VERIFY]/[SRC:] markers --
all deterministic, all zero-tolerance at delivery. Banned words, the "key"
count and paragraph shape stay advisory and never affect the exit code.
Pass --no-gate to force exit 0 for mid-draft runs.

Per SKILL.md, this runs LAST before delivery: after every human merge, every
external rewrite pass, and every Google Docs export or re-import.

If banned-words.json is missing the banned-word scan is skipped with a notice
and the rest still runs.
"""
import sys, os, re, json, argparse

EMOJI = re.compile(
    "[" 
    "\U0001F300-\U0001FAFF"
    "\U00002600-\U000027BF"
    "\U0001F000-\U0001F0FF"
    "\U0000FE00-\U0000FE0F"
    "\U00002190-\U000021FF"
    "\U00002B00-\U00002BFF"
    "]", flags=re.UNICODE)

SMALL_WORDS = {"a","an","the","and","or","but","for","nor","of","to","in","on",
               "at","by","up","as","is","if","vs","per","via","with","from"}

def load_lines(path):
    with open(path, encoding="utf-8") as f:
        return f.read().split("\n")

def find_char(lines, chars, label):
    hits = []
    for i, line in enumerate(lines, 1):
        for ch in chars:
            if ch in line:
                hits.append((i, ch, line.strip()[:90]))
    return hits

def title_case_headings(lines):
    # House-style override: title case is the SDS Manager standard for headings.
    # Heading case is intentionally NOT flagged; kept as a no-op for report compatibility.
    return []
    flagged = []
    for i, line in enumerate(lines, 1):
        m = re.match(r"^(#{1,6})\s+(.*)$", line)
        if not m:
            continue
        text = m.group(2).strip()
        words = [w for w in re.findall(r"[A-Za-z][A-Za-z'\-]*", text)]
        sig = [w for w in words if w.lower() not in SMALL_WORDS and len(w) > 1]
        if len(sig) < 2:
            continue
        # ignore the mandatory first-word capital; look at the rest
        rest = sig[1:]
        if not rest:
            continue
        cap = sum(1 for w in rest if w[0].isupper())
        if cap / len(rest) >= 0.6:
            flagged.append((i, text[:90]))
    return flagged

def key_adjective_count(text):
    # count 'key' as a standalone lowercase word, excluding 'keys'/'keyword'/'keyboard' etc.
    return len(re.findall(r"(?<![A-Za-z])[Kk]ey(?![A-Za-z])", text))

def thematic_breaks(lines):
    return [(i, line.strip()) for i, line in enumerate(lines, 1)
            if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line)]

# Invisible / format Unicode that survives a copy-paste or Docs round-trip.
# Zero-width and bidi controls carry no legitimate meaning in this content;
# NBSP and thin spaces are space homoglyphs that break regex and search.
INVISIBLES = {
    "\u200b": "ZERO WIDTH SPACE",      "\u200c": "ZERO WIDTH NON-JOINER",
    "\u200d": "ZERO WIDTH JOINER",     "\u2060": "WORD JOINER",
    "\ufeff": "BOM / ZWNBSP",          "\u00ad": "SOFT HYPHEN",
    "\u00a0": "NO-BREAK SPACE",        "\u202f": "NARROW NO-BREAK SPACE",
    "\u2009": "THIN SPACE",            "\u200a": "HAIR SPACE",
    "\u2028": "LINE SEPARATOR",        "\u2029": "PARAGRAPH SEPARATOR",
    "\u202a": "LRE", "\u202b": "RLE",  "\u202c": "PDF",
    "\u202d": "LRO", "\u202e": "RLO",
    "\u2066": "LRI", "\u2067": "RLI",  "\u2068": "FSI", "\u2069": "PDI",
}

def invisible_unicode(lines):
    hits = []
    for i, line in enumerate(lines, 1):
        for ch, name in INVISIBLES.items():
            n = line.count(ch)
            if n:
                hits.append((i, name, "U+%04X" % ord(ch), n))
    return hits

DOCS_ARTIFACTS = [
    ("escaped period",           r"\\\."),
    ("escaped bracket",          r"\\[\[\]]"),
    ("space before punctuation", r"\S\s+[.,:;]"),
    ("missing space after colon", r"\w:[A-Za-z]"),
    ("missing space after comma", r",[A-Za-z]"),
    ("double space",             r"[^\n] {2,}[^\n]"),
    ("double period",            r"[^.]\.\.[^.]"),
    ("stray bold pair",          r"\*\* +\*\*"),
]

def docs_artifacts(text):
    out = []
    for name, pat in DOCS_ARTIFACTS:
        n = len(re.findall(pat, text))
        if n:
            out.append((name, n))
    return out

MARKERS = [("[VERIFY]", r"\[VERIFY"), ("[SRC:]", r"\[SRC:")]

def marker_leaks(text):
    return [(name, len(re.findall(pat, text))) for name, pat in MARKERS
            if re.search(pat, text)]

def paragraph_shape(text):
    """Advisory only. Reports paragraphs at 5+ sentences; the skill's own
    paragraph guidance decides whether that is a defect."""
    paras = [p.strip() for p in re.split(r"\n\n+", text)
             if p.strip()
             and not p.strip().startswith(("#", "|", "![", "[VISUAL", "[HERO", ">"))
             and not re.match(r"^(\*|\d+\.|-)\s", p.strip())]
    longs = []
    for p in paras:
        n = len([s for s in re.split(r"(?<=[.!?])\s+", p) if s.strip()])
        if n >= 5:
            longs.append((n, p[:70]))
    return len(paras), longs

def scan_banned(text, banned_path):
    if not os.path.exists(banned_path):
        return None
    with open(banned_path, encoding="utf-8") as f:
        data = json.load(f)
    low = text.lower()
    hits = []
    for w in data.get("words", []):
        term = w["term"].lower()
        # build a word-boundary-ish pattern; allow multi-word terms
        pat = r"(?<![a-z])" + re.escape(term) + r"(?![a-z])"
        n = len(re.findall(pat, low))
        if n:
            hits.append({"term": w["term"], "count": n,
                         "condition": w.get("condition",""),
                         "replace_with": w.get("replace_with"),
                         "note": w.get("note","")})
    return {"hits": hits, "guard": data.get("replacement_overuse_guard",""),
            "key_max": data.get("adjective_key_max_per_article", 2)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--json", action="store_true")
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--banned", default=os.path.join(here, "..", "data", "banned-words.json"))
    ap.add_argument("--no-gate", action="store_true",
                    help="force exit 0 (mid-draft runs); delivery runs must omit this")
    args = ap.parse_args()

    lines = load_lines(args.file)
    text = "\n".join(lines)
    n_paras, long_paras = paragraph_shape(text)

    report = {
        "em_en_dashes": find_char(lines, ["\u2014", "\u2013"], "dash"),
        "curly_quotes": find_char(lines, ["\u201c","\u201d","\u2018","\u2019"], "quote"),
        "emoji": [(i, m.group(0), line.strip()[:80])
                  for i, line in enumerate(lines,1) for m in [EMOJI.search(line)] if m],
        "thematic_breaks": thematic_breaks(lines),
        "title_case_headings": title_case_headings(lines),
        "invisible_unicode": invisible_unicode(lines),
        "docs_artifacts": docs_artifacts(text),
        "marker_leaks": marker_leaks(text),
        "paragraph_total": n_paras,
        "paragraphs_5plus": long_paras,
        "key_adjective_count": key_adjective_count(text),
        "banned": scan_banned(text, args.banned),
    }

    # Blocking set: deterministic, zero-tolerance at delivery.
    blocking = (len(report["em_en_dashes"]) + len(report["curly_quotes"])
                + len(report["emoji"]) + len(report["thematic_breaks"])
                + len(report["invisible_unicode"])
                + sum(n for _, n in report["docs_artifacts"])
                + sum(n for _, n in report["marker_leaks"]))
    report["blocking_count"] = blocking

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return 0 if (args.no_gate or blocking == 0) else 1

    def sec(title, items, fmt):
        print(f"\n== {title} ==")
        if not items:
            print("  clean")
            return
        for it in items:
            print("  " + fmt(it))

    print(f"MECHANICAL SWEEP: {args.file}")
    sec("Em/en dashes (must be zero)", report["em_en_dashes"],
        lambda h: f"L{h[0]}: {h[1]!r}  {h[2]}")
    sec("Curly quotes/apostrophes (must be zero)", report["curly_quotes"],
        lambda h: f"L{h[0]}: {h[1]!r}  {h[2]}")
    sec("Emoji (must be zero)", report["emoji"],
        lambda h: f"L{h[0]}: {h[1]}  {h[2]}")
    sec("Thematic breaks (must be zero)", report["thematic_breaks"],
        lambda h: f"L{h[0]}: {h[1]}")
    sec("Title-case headings (house style: title case is standard - not flagged)",
        report["title_case_headings"], lambda h: f"L{h[0]}: {h[1]}")

    sec("Invisible/format Unicode (must be zero)", report["invisible_unicode"],
        lambda h: f"L{h[0]}: {h[1]} ({h[2]}) x{h[3]}")
    sec("Docs round-trip artifacts (must be zero)", report["docs_artifacts"],
        lambda h: f"{h[0]:28} {h[1]}")
    sec("Marker leaks (must be zero at delivery)", report["marker_leaks"],
        lambda h: f"{h[0]:28} {h[1]}")

    print(f"\n== Paragraph shape (advisory; see the skill's paragraph guidance) ==")
    print(f"  {report['paragraph_total']} body paragraphs, "
          f"{len(report['paragraphs_5plus'])} at 5+ sentences")
    for n, snip in report["paragraphs_5plus"]:
        print(f"    [{n} sent] {snip}...")

    kc = report["key_adjective_count"]
    kmax = report["banned"]["key_max"] if report["banned"] else 2
    print(f"\n== 'key' occurrences: {kc} (adjective guard max {kmax}) ==")
    print("  over guard - reduce" if kc > kmax else "  within guard")

    print("\n== Banned words ==")
    if report["banned"] is None:
        print("  SKIPPED: banned-words.json not found (pass --banned PATH)")
    elif not report["banned"]["hits"]:
        print("  clean")
    else:
        for h in report["banned"]["hits"]:
            cond = f" [only if: {h['condition']}]" if h["condition"] else ""
            rep = h["replace_with"] if h["replace_with"] else "REWRITE (no direct substitute)"
            note = f"  note: {h['note']}" if h["note"] else ""
            print(f"  '{h['term']}' x{h['count']}{cond} -> {rep}{note}")
        print("  (apply condition/note judgment before changing; some bans are context-specific)")

    print("\n" + "=" * 60)
    if blocking == 0:
        print("GATE: PASS - blocking set clean")
    else:
        print(f"GATE: FAIL - {blocking} blocking defect(s); fix before delivery")
        if args.no_gate:
            print("  (--no-gate set: exit forced to 0 for a mid-draft run)")
    return 0 if (args.no_gate or blocking == 0) else 1

if __name__ == "__main__":
    sys.exit(main())
