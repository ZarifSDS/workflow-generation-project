"""Version comparison for the Compare screen (M9 phase 6): a word-level text diff and a rendered view.

- `text_diff` aligns lines, then marks changed words inside replaced lines, and folds long unchanged
  stretches so the changes stand out.
- `rendered_diff` splits both versions into Markdown blocks (paragraphs, headings, lists, figures, FAQ
  and code kept whole), renders each block as the studio does (sanitised), and labels it unchanged,
  added, removed or changed. Changed blocks show the new rendering with the old one available.
"""

import difflib
import re
from dataclasses import dataclass, field

TOKEN_RE = re.compile(r"\s+|\w+|[^\w\s]", re.UNICODE)
CONTEXT = 2  # unchanged lines shown around a change


@dataclass
class Row:
    kind: str  # "same" | "add" | "del" | "change" | "fold"
    segments: list = field(default_factory=list)  # [(op, text)] with op in same/add/del
    count: int = 0  # folded lines


def _words(old, new):
    """[(op, text)] for two strings, by word; whitespace-only changes count as unchanged."""
    a, b = TOKEN_RE.findall(old), TOKEN_RE.findall(new)
    segments = []
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            segments.append(("same", "".join(b[j1:j2])))
            continue
        if i2 > i1:
            segments.append(("del", "".join(a[i1:i2])))
        if j2 > j1:
            segments.append(("add", "".join(b[j1:j2])))
    return _merge(segments)


SIMILAR = 0.5  # share of words two versions of a passage must have in common to diff word by word


def _similar(old, new):
    words_a, words_b = re.findall(r"\w+", old), re.findall(r"\w+", new)
    return difflib.SequenceMatcher(None, words_a, words_b, autojunk=False).ratio() >= SIMILAR


def _merge(segments):
    merged = []
    for op, text in segments:
        if not text:
            continue
        if merged and merged[-1][0] == op:
            merged[-1] = (op, merged[-1][1] + text)
        else:
            merged.append((op, text))
    return merged


def text_diff(old, new):
    """Rows for the text view, plus word counts: (rows, {"added": n, "removed": n})."""
    a, b = old.splitlines(), new.splitlines()
    rows = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            rows.extend(Row("same", [("same", line)]) for line in b[j1:j2])
        elif tag == "insert":
            rows.extend(Row("add", [("add", line)]) for line in b[j1:j2])
        elif tag == "delete":
            rows.extend(Row("del", [("del", line)]) for line in a[i1:i2])
        elif _similar("\n".join(a[i1:i2]), "\n".join(b[j1:j2])):
            rows.append(Row("change", _words("\n".join(a[i1:i2]), "\n".join(b[j1:j2]))))
        else:  # rewritten: interleaving two unrelated sentences word by word is unreadable
            rows.extend(Row("del", [("del", line)]) for line in a[i1:i2])
            rows.extend(Row("add", [("add", line)]) for line in b[j1:j2])
    rows = _fold(rows) if any(row.kind != "same" for row in rows) else []
    stats = {"added": 0, "removed": 0}
    for row in rows:
        for op, text in row.segments:
            if op in ("add", "del"):
                stats["added" if op == "add" else "removed"] += len(re.findall(r"\w+", text))
    return rows, stats


def _fold(rows):
    """Keep CONTEXT unchanged lines next to each change and fold the rest of each unchanged stretch."""
    out, run = [], []

    def flush(at_start, at_end):
        keep_head = 0 if at_start else CONTEXT
        keep_tail = 0 if at_end else CONTEXT
        if len(run) <= keep_head + keep_tail + 1:
            out.extend(run)
        else:
            hidden = len(run) - keep_head - keep_tail
            out.extend([*run[:keep_head], Row("fold", count=hidden), *run[len(run) - keep_tail :]])

    for row in rows:
        if row.kind == "same":
            run.append(row)
            continue
        if run:
            flush(at_start=not out, at_end=False)
            run = []
        out.append(row)
    if run:
        flush(at_start=not out, at_end=True)
    return out


# ---- rendered view ----


def split_blocks(text):
    """Markdown blocks separated by blank lines; FAQ blocks and fenced code stay whole."""
    blocks, current, closer = [], [], None
    for line in (text or "").splitlines():
        stripped = line.strip()
        if closer:
            current.append(line)
            if stripped == closer or (closer == "```" and stripped.startswith("```")):
                blocks.append("\n".join(current))
                current, closer = [], None
            continue
        if stripped == ":::faq" or stripped.startswith("```"):
            if current:
                blocks.append("\n".join(current))
            current, closer = [line], (":::" if stripped == ":::faq" else "```")
            continue
        if not stripped:
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


@dataclass
class Block:
    kind: str  # "same" | "add" | "del" | "change"
    html: str
    old_html: str = ""


def rendered_diff(old, new, render):
    """Blocks of the new version (and removed old blocks), each rendered by `render(markdown) -> html`."""
    a, b = split_blocks(old), split_blocks(new)
    blocks = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            blocks.extend(Block("same", render(text)) for text in b[j1:j2])
        elif tag == "insert":
            blocks.extend(Block("add", render(text)) for text in b[j1:j2])
        elif tag == "delete":
            blocks.extend(Block("del", render(text)) for text in a[i1:i2])
        else:
            olds, news = a[i1:i2], b[j1:j2]
            for index in range(max(len(olds), len(news))):
                if index < len(olds) and index < len(news):
                    blocks.append(Block("change", render(news[index]), render(olds[index])))
                elif index < len(news):
                    blocks.append(Block("add", render(news[index])))
                else:
                    blocks.append(Block("del", render(olds[index])))
    return blocks
