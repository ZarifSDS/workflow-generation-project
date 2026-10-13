#!/usr/bin/env python3
"""
prose_signals.py - countable prose signals that mechanical_sweep.py does not cover.

Replaces the inline heredoc in the original SKILL.md (its dash, quote, invisible
Unicode, marker and paragraph-shape blocks duplicated mechanical_sweep.py and were
dropped). What is left is the part no other script checks:

  - figurative and duty verbs: ai-patterns.md's location-verb, spatial-metaphor and
    vague-idiom rows, plus the lives/sits/runs/bites/houses/holds family used on a
    duty, regulation, document or dataset (not in data/banned-words.json)
  - emphasizers (actually, exactly, really, truly, genuinely, literally), counted
    against the user's "roughly two each per standard-length article" calibration
  - the recurring misses from step-3-edit.md section E2 that a regex can surface:
      * intro scope sentence contains the literal words "this article"
      * FAQ answers that open on a bare "Yes," or "No,"
      * Key Takeaways bullets that lean on this/that/these/those/the same
      * deflection sentences ("check the current...", "confirm the latest...")
  - uncertainty prose that must not survive into publish copy
  - the you/your rate (diagnose flatness by person before rhythm)
  - optional seam dump: every adjacent paragraph pair, for a "why does B follow A" read

Every flag is a prompt to read, never a verdict: literal verb uses are fine, a
pointer word may be resolved inside its own bullet, and a deflection may be a
legitimate trailing qualifier. Always exits 0.

Stdlib only. Reads UTF-8 explicitly (the old heredoc crashed on Windows cp1252 at
the first closing curly quote). Usage:
    python prose_signals.py DRAFT.md [--seams] [--emphasizer-max 2] [--json]
"""
import argparse
import json
import re
import sys

FIGURATIVE = re.compile(
    r"\b(sits?|lives?|runs?|bites?|holds?|houses|reads?|lands?|travels?|"
    r"stretch(?:es)?|turns? on|comes? down to|goes? stale|outlast\w*|earns? its keep|"
    r"hides? a|beats|stands? alone|folds? into)\b", re.I)
EMPHASIZERS = ("actually", "exactly", "really", "truly", "genuinely", "literally")
DEFLECTION = re.compile(
    r"(?i)\b(check|confirm|verify) (the|your) (current|latest|local|state'?s?)\b[^.!?]*[.!?]")
UNCERTAINTY = re.compile(r"(?i)not fully certain|can't confirm|verify before publishing")
YOU = re.compile(r"\b(you|your|yours|you're|you'll|you've)\b", re.I)
POINTER = re.compile(r"(?i)\b(this|that|these|those|the same)\b")
WORD = re.compile(r"[A-Za-z0-9$'-]+")
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+")
SKIP_PREFIX = ("#", "|", "![", "[VISUAL", "[HERO", "<!--", "**Meta", "**Tags", "**Excerpt")
LIST_ITEM = re.compile(r"^(\*|-|\d+\.)\s")
H2 = re.compile(r"(?m)^##\s+(.+?)\s*$")


def body_paragraphs(text):
    out = []
    for line in text.split("\n"):
        s = line.strip()
        if s and not s.startswith(SKIP_PREFIX) and not LIST_ITEM.match(s):
            out.append(s)
    return out


def section(text, heading_re):
    """Text under the first H2 matching heading_re, up to the next H2."""
    heads = list(H2.finditer(text))
    for i, m in enumerate(heads):
        if re.search(heading_re, m.group(1), re.I):
            end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
            return text[m.end():end]
    return None


def intro(text):
    """Prose between the H1/metadata block and the first H2."""
    m = H2.search(text)
    head = text[:m.start()] if m else text
    return "\n".join(p for p in body_paragraphs(head))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--seams", action="store_true", help="print every adjacent paragraph pair")
    ap.add_argument("--emphasizer-max", type=int, default=2)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass

    with open(a.file, encoding="utf-8") as f:
        t = f.read()

    fig = []
    for s in SENT_SPLIT.split(t):
        for m in FIGURATIVE.finditer(s):
            fig.append({"verb": m.group(0), "sentence": " ".join(s.split())[:100]})

    emph = {}
    for w in EMPHASIZERS:
        n = len(re.findall(r"\b" + w + r"\b", t, re.I))
        if n:
            emph[w] = n
    emph_over = {w: n for w, n in emph.items() if n > a.emphasizer_max}

    intro_text = intro(t)
    has_this_article = bool(re.search(r"(?i)\bthis article\b", intro_text)) if intro_text else None

    faq = section(t, r"frequently asked questions")
    bare_yes_no = []
    if faq:
        for block in re.split(r"(?m)^###\s+", faq)[1:]:
            q, _, ans = block.partition("\n")
            first = ans.strip().split("\n")[0] if ans.strip() else ""
            if re.match(r"(?i)^(yes|no)\b[,.]", first):
                bare_yes_no.append({"question": q.strip()[:80], "answer_start": first[:80]})

    kt = section(t, r"key takeaways")
    kt_pointers = []
    if kt:
        for line in kt.split("\n"):
            s = line.strip()
            if LIST_ITEM.match(s) and POINTER.search(s):
                kt_pointers.append({"words": sorted({m.group(0).lower() for m in POINTER.finditer(s)}),
                                    "bullet": s[:100]})

    deflect = [" ".join(m.group(0).split())[:100] for m in DEFLECTION.finditer(t)]
    unc = [m.group(0) for m in UNCERTAINTY.finditer(t)]
    words = len(WORD.findall(t))
    yous = len(YOU.findall(t))
    rate = (words // yous) if yous else None

    seams = []
    if a.seams:
        ps = body_paragraphs(t)
        for x, y in zip(ps, ps[1:]):
            seams.append({"a_end": SENT_SPLIT.split(x)[-1][-80:],
                          "b_start": SENT_SPLIT.split(y)[0][:80]})

    report = {"figurative_verbs": fig, "emphasizers": emph,
              "emphasizers_over_max": emph_over, "emphasizer_max": a.emphasizer_max,
              "intro_has_this_article": has_this_article,
              "faq_bare_yes_no": bare_yes_no, "key_takeaway_pointers": kt_pointers,
              "deflection_candidates": deflect, "uncertainty_prose": unc,
              "words": words, "you_count": yous, "words_per_you": rate, "seams": seams}

    if a.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return 0

    print(f"PROSE SIGNALS: {a.file}")
    print("\n== Figurative and duty verbs (read each; literal uses are fine) ==")
    print("  none" if not fig else "\n".join(f"  [{h['verb']}] {h['sentence']}" for h in fig))
    print(f"\n== Emphasizers (calibration: roughly {a.emphasizer_max} each; cut any that add nothing) ==")
    if not emph:
        print("  none")
    for w, n in emph.items():
        print(f"  {w}: {n}" + ("  <- over" if w in emph_over else ""))
    print("\n== Intro scope sentence contains \"this article\" ==")
    print("  no intro found" if has_this_article is None else ("  yes" if has_this_article else "  NO"))
    print("\n== FAQ answers opening on a bare Yes/No ==")
    print("  none" if not bare_yes_no else "\n".join(
        f"  Q: {b['question']}\n     A: {b['answer_start']}" for b in bare_yes_no))
    print("\n== Key Takeaways bullets with pointer words (resolved inside the bullet?) ==")
    print("  none" if not kt_pointers else "\n".join(
        f"  [{', '.join(b['words'])}] {b['bullet']}" for b in kt_pointers))
    print("\n== Deflection candidates (entire payload, or a trailing qualifier?) ==")
    print("  none" if not deflect else "\n".join(f"  {d}" for d in deflect))
    print("\n== Uncertainty prose (must be zero in publish copy) ==")
    print("  none" if not unc else "  " + ", ".join(unc))
    print("\n== Reader address ==")
    if rate:
        print(f"  {words} words, {yous} you/your = 1 per {rate} words "
              "(user's calibration: roughly 1 per 150-200, clustered at section closes and FAQ)")
    else:
        print(f"  {words} words, no second-person pronouns: check person before rhythm")
    if a.seams:
        print("\n== Seams: read each pair and ask why B follows A ==")
        for s in seams:
            print(f"  A ...{s['a_end']}\n  B {s['b_start']}...\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
