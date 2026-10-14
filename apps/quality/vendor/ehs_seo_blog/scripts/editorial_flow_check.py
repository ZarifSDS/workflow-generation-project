#!/usr/bin/env python3
"""Report deterministic signals related to reader-first and GEO editorial flow.

The script checks what can be counted reliably and produces review prompts for
the judgment calls that still require reading. Signals include H3 question
coverage, unresolved H3 openers, incomplete abstract assertions, and examples
that begin before their concept is introduced. It never rewrites and always
exits zero.

Usage:
    python3 editorial_flow_check.py DRAFT.md [--max-takeaways 7] [--json]
"""
import argparse
import json
import re
from pathlib import Path


HEADING = re.compile(r"^(#{1,6})\s+\**(.+?)\**\s*$")
LIST_ITEM = re.compile(r"^\s*[*+-]\s+(.+)$")
META_DESCRIPTION = re.compile(
    r"^\*\*Meta Description:\*\*\s*(.+?)\s*$", re.MULTILINE
)
SCOPE_START = re.compile(
    r"^(By the end|After reading|When you finish|You'll (?:know|understand|be able))\b",
    re.IGNORECASE,
)
QUESTION_FRAGMENT = re.compile(
    r"(?:^|[.!?]\s+)(What|Who|Why|How|Where|When)\b[^?]*(?:\.|$)",
    re.IGNORECASE,
)
DEFINITE_NOUN = re.compile(
    r"^The\s+(department|system|program|process|framework|regulation|standard|"
    r"agency|requirement|duty|role)\b",
    re.IGNORECASE,
)
H3_OPENING_PRONOUN = re.compile(
    r"^(This|That|These|Those|It|They)\b", re.IGNORECASE
)
ABSTRACT_SUBJECT = re.compile(
    r"^(?:This|That|These|Those|The)\s+"
    r"(?:field|boundar(?:y|ies)|consequence(?:s)?|comparison|distinction|"
    r"relationship|reverse|effect|structure|sequence|process|cycle|result|"
    r"point|answer|pattern|interpretation)\b",
    re.IGNORECASE,
)
EXPLANATION_SIGNAL = re.compile(
    r"\b(because|by|through|when|where|which|how|why|whether)\b|[:;]",
    re.IGNORECASE,
)
CONTEXTLESS_EXAMPLE = re.compile(
    r"^(?:A|An)\s+[^.!?]{0,90}\b(?:shows|demonstrates|illustrates)\s+"
    r"(?:how|why|that)\b",
    re.IGNORECASE,
)
STAT_SIGNAL = re.compile(r"\[SRC:|\\\[SRC:|\b\d[\d,.%$]*\b", re.IGNORECASE)
STOP = {
    "a", "an", "and", "are", "as", "at", "be", "because", "but", "by", "for",
    "from", "has", "have", "in", "is", "it", "its", "of", "on", "or", "that",
    "the", "their", "these", "this", "to", "was", "were", "which", "while",
    "who", "with", "you", "your",
}


def clean_inline(text):
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\\\[SRC:.*?\\\]", "", text)
    text = re.sub(r"\[SRC:.*?\]", "", text)
    text = re.sub(r"\\([\\&.])", r"\1", text)
    return re.sub(r"[*_`]", "", text).strip()


def sentences(text):
    flat = re.sub(r"\s+", " ", clean_inline(text)).strip()
    if not flat:
        return []
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", flat)
        if part.strip()
    ]


def content_words(text):
    return {
        w for w in re.findall(r"[a-z][a-z'-]+", clean_inline(text).lower())
        if w not in STOP and len(w) > 2
    }


def blocks(lines):
    result = []
    current = []
    start = 1
    kind = "prose"

    def flush():
        nonlocal current, start, kind
        if current:
            result.append({
                "kind": kind,
                "line": start,
                "text": " ".join(x.strip() for x in current),
            })
            current = []

    for number, line in enumerate(lines, 1):
        heading = HEADING.match(line)
        item = LIST_ITEM.match(line)
        if heading:
            flush()
            result.append({
                "kind": "heading",
                "line": number,
                "level": len(heading.group(1)),
                "text": clean_inline(heading.group(2)),
            })
            kind = "prose"
        elif item:
            if kind != "list":
                flush()
                start = number
                kind = "list"
            current.append(item.group(1))
        elif not line.strip():
            flush()
            kind = "prose"
        else:
            if not current:
                start = number
            if kind == "list":
                flush()
                start = number
                kind = "prose"
            current.append(line)
    flush()
    return result


def section(lines, heading_name):
    start = None
    level = None
    collected = []
    for line in lines:
        match = HEADING.match(line)
        if match:
            name = clean_inline(match.group(2)).lower()
            current_level = len(match.group(1))
            if start is not None and current_level <= level:
                break
            if name == heading_name.lower():
                start = True
                level = current_level
                continue
        if start is not None:
            collected.append(line)
    return collected


def intro_lines(lines):
    metadata_seen = False
    link_map = False
    collected = []
    for line in lines:
        match = HEADING.match(line)
        if match and len(match.group(1)) == 1:
            continue
        if re.match(r"^\*\*(Meta Title|Meta Description|Slug|Tags|Excerpt):\*\*", line):
            metadata_seen = True
            continue
        if line.strip() == "**Editorial Link Opportunities**":
            link_map = True
            continue
        if line.strip() == "<!-- END EDITORIAL LINK OPPORTUNITIES -->":
            link_map = False
            continue
        if link_map:
            continue
        if match and len(match.group(1)) == 2:
            break
        if metadata_seen and line.strip() and not line.startswith("**"):
            collected.append(line)
    return collected


def overlap_flags(parsed):
    flags = []
    for index, block in enumerate(parsed):
        if block["kind"] != "list" or index == 0:
            continue
        previous = parsed[index - 1]
        if previous["kind"] != "prose":
            continue
        pwords = content_words(previous["text"])
        lwords = content_words(block["text"])
        shared = pwords & lwords
        if min(len(pwords), len(lwords)) >= 5:
            ratio = len(shared) / min(len(pwords), len(lwords))
            if ratio >= 0.20 and len(shared) >= 5:
                flags.append({
                    "line": block["line"],
                    "overlap_ratio": round(ratio, 2),
                    "shared_terms": sorted(shared)[:12],
                })
    return flags


def unresolved_definite_nouns(parsed):
    flags = []
    recent = ""
    current_heading = ""
    blocks_since_heading = 0
    for block in parsed:
        if block["kind"] == "heading":
            current_heading = block["text"]
            blocks_since_heading = 0
            continue
        first = sentences(block["text"])
        if not first:
            continue
        blocks_since_heading += 1
        match = DEFINITE_NOUN.match(first[0])
        if match:
            noun = match.group(1).lower()
            heading_introduces_first_block = (
                blocks_since_heading == 1 and noun in current_heading.lower()
            )
            if noun not in recent.lower() and not heading_introduces_first_block:
                flags.append({
                    "line": block["line"],
                    "noun": noun,
                    "sentence": first[0][:180],
                })
        recent = f"{recent} {block['text']}"[-800:]
    return flags


def h3_geo_report(parsed, raw):
    h3s = [
        (index, block)
        for index, block in enumerate(parsed)
        if block["kind"] == "heading" and block.get("level") == 3
    ]
    question_count = sum(
        1 for _, block in h3s if block["text"].rstrip().endswith("?")
    )
    h1 = next(
        (
            block["text"].lower()
            for block in parsed
            if block["kind"] == "heading" and block.get("level") == 1
        ),
        "",
    )
    broad_what_is = h1.startswith("what is ")
    opener_flags = []
    for index, heading in h3s:
        opener = None
        for candidate in parsed[index + 1:]:
            if candidate["kind"] == "heading":
                break
            if candidate["kind"] == "prose":
                first = sentences(candidate["text"])
                if first:
                    opener = first[0]
                    break
        if not opener:
            opener_flags.append({
                "line": heading["line"],
                "heading": heading["text"],
                "reason": "no prose answer before the next heading",
            })
        elif H3_OPENING_PRONOUN.match(opener):
            opener_flags.append({
                "line": heading["line"],
                "heading": heading["text"],
                "reason": f"opener begins with unresolved shorthand: {opener[:140]}",
            })
    ratio = question_count / len(h3s) if h3s else 0
    return {
        "total": len(h3s),
        "questions": question_count,
        "ratio": round(ratio, 2),
        "broad_what_is": broad_what_is,
        "majority_flag": broad_what_is and bool(h3s) and ratio <= 0.5,
        "opener_flags": opener_flags,
        "editorial_link_map_present": bool(
            re.search(r"(?m)^\*\*Editorial Link Opportunities\*\*\s*$", raw)
        ),
    }


def incomplete_abstract_assertions(parsed):
    flags = []
    for block in parsed:
        if block["kind"] != "prose":
            continue
        for sentence in sentences(block["text"]):
            word_count = len(re.findall(r"\b[\w'-]+\b", sentence))
            if (
                word_count <= 12
                and ABSTRACT_SUBJECT.match(sentence)
                and not EXPLANATION_SIGNAL.search(sentence)
            ):
                flags.append({
                    "line": block["line"],
                    "sentence": sentence[:180],
                })
    return flags


def contextless_example_openers(parsed):
    flags = []
    for block in parsed:
        if block["kind"] != "prose":
            continue
        first = sentences(block["text"])
        if first and CONTEXTLESS_EXAMPLE.match(first[0]):
            flags.append({
                "line": block["line"],
                "sentence": first[0][:180],
            })
    return flags


def transition_pairs(parsed):
    sections = []
    current = None
    for block in parsed:
        if block["kind"] == "heading" and block.get("level") == 2:
            if current:
                sections.append(current)
            current = {"heading": block["text"], "text": []}
        elif current and block["kind"] in {"prose", "list"}:
            current["text"].append(block["text"])
    if current:
        sections.append(current)
    pairs = []
    for left, right in zip(sections, sections[1:]):
        left_sentences = sentences(" ".join(left["text"]))
        right_sentences = sentences(" ".join(right["text"]))
        if left_sentences and right_sentences:
            pairs.append({
                "from": left["heading"],
                "last": left_sentences[-1][:180],
                "to": right["heading"],
                "first": right_sentences[0][:180],
            })
    return pairs


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("file")
    parser.add_argument("--max-takeaways", type=int, default=7)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    path = Path(args.file)
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines()
    parsed = blocks(lines)

    meta_match = META_DESCRIPTION.search(raw)
    meta = clean_inline(meta_match.group(1)) if meta_match else ""
    meta_flags = []
    if not meta:
        meta_flags.append("missing")
    else:
        if not re.search(r"[.!?]$", meta):
            meta_flags.append("does not end with sentence punctuation")
        if QUESTION_FRAGMENT.search(meta):
            meta_flags.append("possible question-word fragment")

    takeaway = section(lines, "Key Takeaways")
    takeaway_count = sum(1 for line in takeaway if LIST_ITEM.match(line))

    intro_text = " ".join(intro_lines(lines))
    intro_sentences = sentences(intro_text)
    scope_after_stat = []
    for index, sentence in enumerate(intro_sentences):
        if SCOPE_START.match(sentence) and index and STAT_SIGNAL.search(intro_sentences[index - 1]):
            scope_after_stat.append({
                "scope_sentence": sentence[:180],
                "previous_sentence": intro_sentences[index - 1][:180],
            })

    report = {
        "file": str(path),
        "meta_description": {
            "characters": len(meta),
            "flags": meta_flags,
        },
        "key_takeaways": {
            "count": takeaway_count,
            "maximum": args.max_takeaways,
            "flag": takeaway_count > args.max_takeaways,
        },
        "on_this_page_present": bool(
            re.search(r"(?mi)^##\s+\**On This Page\**\s*$", raw)
        ),
        "scope_sentence_directly_after_statistic": scope_after_stat,
        "possible_prose_list_duplication": overlap_flags(parsed),
        "possible_unintroduced_definite_nouns": unresolved_definite_nouns(parsed),
        "h3_geo": h3_geo_report(parsed, raw),
        "incomplete_abstract_assertions": incomplete_abstract_assertions(parsed),
        "contextless_example_openers": contextless_example_openers(parsed),
        "section_transition_review": transition_pairs(parsed),
    }

    if args.json:
        print(json.dumps(report, indent=2, ensure_ascii=True))
        return

    print(f"EDITORIAL FLOW CHECK: {path}")
    md = report["meta_description"]
    print(f"\nMeta description: {md['characters']} characters")
    print("  clean" if not md["flags"] else "  FLAG: " + "; ".join(md["flags"]))

    kt = report["key_takeaways"]
    status = "FLAG: reduce" if kt["flag"] else "within maximum"
    print(f"\nKey Takeaways: {kt['count']} (maximum {kt['maximum']}) - {status}")
    nav = "present; confirm it adds value" if report["on_this_page_present"] else "absent"
    print(f"On This Page block: {nav}")

    print("\n== Scope sentence directly after a statistic ==")
    if not scope_after_stat:
        print("  clean")
    for item in scope_after_stat:
        print(f"  FLAG: {item['previous_sentence']} -> {item['scope_sentence']}")

    print("\n== Possible prose/list duplication ==")
    duplicates = report["possible_prose_list_duplication"]
    if not duplicates:
        print("  clean")
    for item in duplicates:
        print(
            f"  L{item['line']}: overlap {item['overlap_ratio']} "
            f"({', '.join(item['shared_terms'])})"
        )

    print("\n== Possible unintroduced definite nouns ==")
    unresolved = report["possible_unintroduced_definite_nouns"]
    if not unresolved:
        print("  clean")
    for item in unresolved:
        print(f"  L{item['line']}: '{item['noun']}' in {item['sentence']}")

    geo = report["h3_geo"]
    print("\n== H3 GEO structure ==")
    print(
        f"  Question H3s: {geo['questions']}/{geo['total']} "
        f"({geo['ratio']:.0%})"
    )
    if geo["majority_flag"]:
        print("  FLAG: broad 'what is' content should use question-shaped H3s for a majority of genuine subqueries")
    if not geo["opener_flags"]:
        print("  H3 openers: clean")
    for item in geo["opener_flags"]:
        print(f"  L{item['line']}: {item['heading']} - {item['reason']}")
    link_map = "present" if geo["editorial_link_map_present"] else "absent"
    print(f"  Editorial link map: {link_map}")

    print("\n== Incomplete abstract assertions ==")
    abstract = report["incomplete_abstract_assertions"]
    if not abstract:
        print("  clean")
    for item in abstract:
        print(f"  L{item['line']}: {item['sentence']}")

    print("\n== Contextless example openers ==")
    examples = report["contextless_example_openers"]
    if not examples:
        print("  clean")
    for item in examples:
        print(f"  L{item['line']}: {item['sentence']}")

    print("\n== H2 transition pairs for reader review ==")
    for item in report["section_transition_review"]:
        print(f"  {item['from']} -> {item['to']}")
        print(f"    last:  {item['last']}")
        print(f"    first: {item['first']}")

    print(
        "\nHeuristics are review prompts, not automatic rewrite instructions. "
        "Read the flagged pair in context before changing it."
    )


if __name__ == "__main__":
    main()
