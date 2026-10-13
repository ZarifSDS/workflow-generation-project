#!/usr/bin/env python3
"""
metrics.py - deterministic Step 3H / draft-analysis metrics.

Reports Flesch-Kincaid Grade Level, primary/secondary keyword frequency and
density, and a sentence-length distribution (mean, spread, and a small
histogram). These are informational, never pass/fail gates. The 2% primary
keyword level is an anti-stuffing warning, not a minimum to reach.

Stdlib only, no external NLP deps (self-contained syllable heuristic). Usage:
    python3 metrics.py DRAFT.md --pkeyword "SDS retention period" [--skeyword "safety data sheet storage"] [--fkgl 8] [--json]

Markdown is lightly stripped (code fences, headings markers, link syntax,
table pipes) before counting so structure doesn't skew readability.
"""
import sys, re, json, argparse

def strip_markdown(text):
    text = re.sub(r"```.*?```", " ", text, flags=re.S)      # code fences
    text = re.sub(r"`[^`]*`", " ", text)                     # inline code
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)        # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)     # links -> anchor text
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)  # heading markers
    text = re.sub(r"[*_>#|]", " ", text)                      # md punctuation
    text = re.sub(r"^\s*[-+]\s+", "", text, flags=re.M)       # bullet markers
    return text

def split_sentences(text):
    # collapse whitespace, split on sentence enders followed by space/EOL
    text = re.sub(r"\s+", " ", text).strip()
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text)
    return [p.strip() for p in parts if re.search(r"[A-Za-z]", p)]

def count_syllables(word):
    word = word.lower()
    word = re.sub(r"[^a-z]", "", word)
    if not word:
        return 0
    groups = re.findall(r"[aeiouy]+", word)
    n = len(groups)
    if word.endswith("e") and not word.endswith(("le","ee","ie")) and n > 1:
        n -= 1
    return max(1, n)

def fkgl(sentences):
    words = []
    for s in sentences:
        words += re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", s)
    nwords = len(words)
    nsent = max(1, len(sentences))
    nsyll = sum(count_syllables(w) for w in words)
    if nwords == 0:
        return 0.0, 0, 0
    grade = 0.39 * (nwords / nsent) + 11.8 * (nsyll / nwords) - 15.59
    return round(grade, 2), nwords, nsent

def keyword_stats(text, phrase, total_words):
    if not phrase:
        return None
    pat = re.compile(r"(?<![A-Za-z])" + re.escape(phrase.lower()) + r"(?![A-Za-z])")
    n = len(pat.findall(text.lower()))
    phrase_words = len(phrase.split())
    density = round(100.0 * n * phrase_words / total_words, 2) if total_words else 0.0
    return {"phrase": phrase, "count": n, "density_pct": density}

def length_distribution(sentences):
    lens = [len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", s)) for s in sentences]
    if not lens:
        return {}
    buckets = {"1-8":0,"9-15":0,"16-24":0,"25+":0}
    for L in lens:
        if L <= 8: buckets["1-8"] += 1
        elif L <= 15: buckets["9-15"] += 1
        elif L <= 24: buckets["16-24"] += 1
        else: buckets["25+"] += 1
    mean = round(sum(lens)/len(lens), 1)
    spread = max(lens) - min(lens)
    # crude flatness signal: most sentences in one bucket
    dominant = max(buckets.values()) / len(lens)
    return {"count": len(lens), "mean": mean, "min": min(lens), "max": max(lens),
            "spread": spread, "buckets": buckets,
            "flatness_ratio": round(dominant, 2)}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--pkeyword", default="")
    ap.add_argument("--skeyword", default="")
    ap.add_argument("--fkgl", type=float, default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    with open(args.file, encoding="utf-8") as f:
        raw = f.read()
    text = strip_markdown(raw)
    sentences = split_sentences(text)
    grade, nwords, nsent = fkgl(sentences)

    report = {
        "fkgl": grade, "target_fkgl": args.fkgl, "words": nwords, "sentences": nsent,
        "pkeyword": keyword_stats(text, args.pkeyword, nwords),
        "skeyword": keyword_stats(text, args.skeyword, nwords),
        "sentence_length": length_distribution(sentences),
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True)); return

    print(f"METRICS: {args.file}")
    print(f"\nWords: {nwords}   Sentences: {nsent}")
    tgt = f" (target ~{args.fkgl})" if args.fkgl is not None else ""
    print(f"Flesch-Kincaid Grade Level: {grade}{tgt}   [heuristic - informational only]")

    pk = report["pkeyword"]
    if pk:
        flag = "  <-- review for stuffing; 2% is a ceiling guide" if pk["density_pct"] > 2.0 else ""
        print(f"\nPKEYWORD '{pk['phrase']}': {pk['count']} occurrences, density {pk['density_pct']}%{flag}")
    sk = report["skeyword"]
    if sk:
        if sk["count"] > 1:
            flag = "  <-- reduce to one natural use"
        elif sk["count"] == 0:
            flag = "  <-- place once only if it reads naturally; otherwise report the omission"
        else:
            flag = ""
        print(f"SKEYWORD '{sk['phrase']}': {sk['count']} occurrences{flag}")

    sl = report["sentence_length"]
    if sl:
        print(f"\nSentence length: mean {sl['mean']}, range {sl['min']}-{sl['max']} (spread {sl['spread']})")
        print(f"  buckets: {sl['buckets']}")
        if sl["flatness_ratio"] >= 0.7:
            print(f"  FLATNESS WARNING: {int(sl['flatness_ratio']*100)}% of sentences in one length band - vary cadence")
        else:
            print(f"  variation looks healthy (flatness {sl['flatness_ratio']})")
    print("\nAll figures are calibration aids, not gates.")

if __name__ == "__main__":
    main()
