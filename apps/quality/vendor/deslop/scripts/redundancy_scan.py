#!/usr/bin/env python3
"""Find information restated across different sections of one document.

Long articles repeat themselves in a way no lexical or structural check sees:
the same fact, phrased almost identically, in two sections that each felt right
in isolation. A reader hits it as deja vu and stops trusting the writer.

  python redundancy_scan.py FILE [--n 6] [--json]

Standard library only. Repetition inside a single section is fine (that is
emphasis); repetition across sections is what this reports.
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

FENCE_RE = re.compile(r"```.*?```", re.S)
COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
TABLE_RE = re.compile(r"(?m)^\s*\|.*$")
HEAD_RE = re.compile(r"(?m)^(#{2,6})\s+(.+?)\s*$")
WORD_RE = re.compile(r"[a-z0-9']+")

# Quoted statutory text and enumerated source lists are supposed to recur.
EXEMPT = re.compile(r"high risk construction work|work health and safety", re.I)


def sections(text: str):
    t = COMMENT_RE.sub(" ", FENCE_RE.sub(" ", text))
    t = TABLE_RE.sub("", t)
    parts, out, cur = HEAD_RE.split(t), [], ("(preamble)", "")
    if parts and parts[0].strip():
        out.append(("(preamble)", parts[0]))
    for i in range(1, len(parts) - 2, 3):
        out.append((parts[i + 1].strip(), parts[i + 2]))
    return out


def scan(text: str, n: int = 6):
    secs = sections(text)
    grams = collections.defaultdict(set)
    for name, body in secs:
        w = WORD_RE.findall(body.lower())
        for i in range(len(w) - n + 1):
            grams[" ".join(w[i : i + n])].add(name)

    # collapse overlapping n-grams that share the same section pair
    raw = {g: fr for g, fr in grams.items() if len(fr) > 1 and not EXEMPT.search(g)}
    merged, used = [], set()
    for g in sorted(raw, key=len, reverse=True):
        if g in used:
            continue
        pair = raw[g]
        family = [h for h in raw if raw[h] == pair and (h in g or g in h or
                  len(set(h.split()) & set(g.split())) >= n - 2)]
        used.update(family)
        longest = max(family, key=len)
        merged.append({"phrase": longest, "sections": sorted(pair),
                       "variants": len(family)})

    merged.sort(key=lambda d: -len(d["phrase"]))
    return {"sections": len(secs), "n": n, "findings": merged}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--n", type=int, default=6, help="n-gram length (default 6)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    p = Path(a.file)
    if not p.is_file():
        print(f"error: not a file: {p}", file=sys.stderr)
        return 2
    res = scan(p.read_text(encoding="utf-8", errors="replace"), a.n)
    res["file"] = str(p)

    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    print(f"{p.name}  |  {res['sections']} sections  |  {a.n}-gram overlap\n")
    if not res["findings"]:
        print("No cross-section repetition found. Repetition of core entity names "
              "is normal and is not reported.")
        return 0
    for f in res["findings"]:
        span = f"{f['variants']} overlapping phrases" if f["variants"] > 1 else "1 phrase"
        print(f"[{span}]  \"{f['phrase']}\"")
        for s in f["sections"]:
            print(f"      {s}")
        print()
    print("Decide per finding: a fact restated for a reader who arrived mid-page is "
          "fine (FAQ answers, Key Takeaways). The same sentence in two adjacent body "
          "sections is not - keep the fuller treatment and cut the other to a clause.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
