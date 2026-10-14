#!/usr/bin/env python3
"""
link_check.py - deterministic Step 3I linking checks.

Reports internal (sdsmanager.com) vs external link counts, flags the placement
violations that are mechanical (two links in one sentence, two consecutive
links in a paragraph, more than one internal link in a section), flags likely
link-only sentences, and identifies which product-link-registry page each
internal product link points at.

Reference-list entries and the review-only Editorial Link Opportunities block
are excluded from prose-placement checks. References still count as external
links in the inventory.

Judgment calls (is the anchor a natural noun phrase? does the link solve a
problem the section raised?) stay with the model - this only catches the
countable violations.

Stdlib only. Usage:
    python3 link_check.py DRAFT.md [--internal-domain sdsmanager.com] [--registry PATH] [--json]
"""
import sys, os, re, json, argparse

LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")

def load(path):
    with open(path, encoding="utf-8") as f:
        return f.read()

def sentences_with_links(text):
    # split into rough sentences keeping link markup intact
    flat = re.sub(r"\s+", " ", text)
    parts = re.split(r"(?<=[.!?])\s+", flat)
    return parts

def prose_for_placement_checks(text):
    text = re.sub(
        r"(?ms)^\*\*Editorial Link Opportunities\*\*\s*.*?"
        r"^<!-- END EDITORIAL LINK OPPORTUNITIES -->\s*",
        "",
        text,
    )
    return re.split(r"(?m)^##\s+References\s*$", text, maxsplit=1)[0]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--internal-domain", default="sdsmanager.com")
    here = os.path.dirname(os.path.abspath(__file__))
    ap.add_argument("--registry", default=os.path.join(here, "..", "data", "product-link-registry.json"))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    text = load(args.file)
    prose_text = prose_for_placement_checks(text)
    all_links = LINK.findall(text)
    internal = [(a,u) for a,u in all_links if args.internal_domain in u]
    external = [(a,u) for a,u in all_links if args.internal_domain not in u]

    # two links in one sentence
    two_in_sentence = []
    for s in sentences_with_links(prose_text):
        if len(LINK.findall(s)) >= 2:
            two_in_sentence.append(s.strip()[:120])

    # consecutive links in a paragraph (two links with only short glue between)
    consecutive = []
    for para in prose_text.split("\n\n"):
        links = list(LINK.finditer(para))
        for x in range(len(links)-1):
            between = para[links[x].end():links[x+1].start()]
            if len(re.findall(r"[A-Za-z]+", between)) <= 3:
                consecutive.append(para.strip()[:120])
                break

    # link-only sentences: sentence is essentially just the link + filler
    link_only = []
    for s in sentences_with_links(prose_text):
        ms = LINK.findall(s)
        if not ms:
            continue
        stripped = LINK.sub("", s)
        words = re.findall(r"[A-Za-z]+", stripped)
        if len(words) <= 4 or re.search(r"\b(for more|read more|learn more|click here|see our|find out)\b", s, re.I):
            link_only.append(s.strip()[:120])

    # per-section internal link count (# heading delimited)
    sections = re.split(r"(?m)^#{1,6}\s+", prose_text)
    multi_internal_sections = []
    for sec in sections:
        n = sum(1 for a,u in LINK.findall(sec) if args.internal_domain in u)
        if n > 1:
            head = sec.strip().split("\n",1)[0][:70]
            multi_internal_sections.append((head, n))

    # registry identification: pick the single most-specific (longest-URL) match per link
    registry_hits = []
    if os.path.exists(args.registry):
        reg = json.load(open(args.registry, encoding="utf-8"))
        pages = reg.get("pages", [])
        for a, u in internal:
            u_norm = re.sub(r"/[a-z]{2}/", "/us/", u)  # normalize region slug to /us/
            best = None
            for p in pages:
                if p["url"] in u_norm and (best is None or len(p["url"]) > len(best["url"])):
                    best = p
            if best:
                registry_hits.append({"anchor": a, "url": u, "page": best["name"], "level": best["level"]})

    report = {
        "internal_count": len(internal), "external_count": len(external),
        "internal": internal, "external": external,
        "two_links_one_sentence": two_in_sentence,
        "consecutive_links": consecutive,
        "link_only_sentences": link_only,
        "sections_over_one_internal": multi_internal_sections,
        "registry_matches": registry_hits,
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True)); return

    print(f"LINK CHECK: {args.file}")
    print(f"\nInternal ({args.internal_domain}): {len(internal)}   External: {len(external)}")
    print("  internal minimum is 3 - FLAG shortfall" if len(internal) < 3 else "  internal minimum (3) met")
    for a,u in internal:
        print(f"    [int] {a}  ->  {u}")
    for a,u in external:
        print(f"    [ext] {a}  ->  {u}")

    def sec(title, items, fmt=lambda x: x):
        print(f"\n== {title} ==")
        print("  clean" if not items else "")
        for it in items: print("  " + fmt(it))

    sec("Two links in one sentence (banned)", two_in_sentence)
    sec("Consecutive links in a paragraph (banned)", consecutive)
    sec("Likely link-only sentences (banned - every link rides a sentence with its own value)", link_only)
    sec("Sections with more than one internal link (max 1 per H2)",
        multi_internal_sections, lambda t: f"'{t[0]}' has {t[1]}")
    print("\n== Product-registry links identified ==")
    if not registry_hits:
        print("  none matched")
    else:
        for h in registry_hits:
            print(f"  {h['page']} ({h['level']}): {h['anchor']} -> {h['url']}")
        levels = {h["level"] for h in registry_hits}
        if "platform" in levels and "module" in levels:
            print("  NOTE: both landing and module pages linked - confirm deepest-page-wins isn't violated")

if __name__ == "__main__":
    main()
