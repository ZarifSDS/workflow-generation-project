"""Turn a filled scorecard plus results.json into a ranked results table."""

import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import mean

from .runner import RUBRIC

START, END = "<!-- eval-results:start -->", "<!-- eval-results:end -->"


def parse_scorecard(text):
    """Return {brief_id: {label: {criterion: score, "Notes": str}}}; blank cells are skipped."""
    scores, brief_id = {}, None
    for line in text.splitlines():
        heading = re.match(r"^##\s+(\S+)", line)
        if heading:
            brief_id = heading.group(1)
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not brief_id or len(cells) < len(RUBRIC) + 1 or not re.fullmatch(r"[A-Z]", cells[0]):
            continue
        row = {}
        for criterion, cell in zip(RUBRIC, cells[1 : len(RUBRIC) + 1], strict=True):
            if re.fullmatch(r"[1-5](\.\d)?", cell):
                row[criterion] = float(cell)
        if len(cells) > len(RUBRIC) + 1 and cells[len(RUBRIC) + 1]:
            row["Notes"] = cells[len(RUBRIC) + 1]
        scores.setdefault(brief_id, {})[cells[0]] = row
    return scores


def summarise(run_dir):
    run_dir = Path(run_dir)
    key = json.loads((run_dir / "key.json").read_text(encoding="utf-8"))
    results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
    scores = parse_scorecard((run_dir / "scorecard.md").read_text(encoding="utf-8"))

    per_model = defaultdict(lambda: defaultdict(list))
    for brief_id, labels in key.items():
        for label, candidate in labels.items():
            name = f"{candidate['provider']}/{candidate['model']}"
            row = scores.get(brief_id, {}).get(label, {})
            for criterion in RUBRIC:
                if criterion in row:
                    per_model[name][criterion].append(row[criterion])
            result = results.get(brief_id, {}).get(label, {})
            per_model[name]["status"].append(result.get("status", "missing"))
            if result.get("total_time"):
                per_model[name]["time"].append(result["total_time"])
            if result.get("tokens_per_second"):
                per_model[name]["tps"].append(result["tokens_per_second"])
            m = result.get("metrics") or {}
            if m.get("fkgl") is not None and m.get("fkgl_target"):
                per_model[name]["fkgl_gap"].append(abs(m["fkgl"] - m["fkgl_target"]))
            if m:
                per_model[name]["red_flags"].append(sum(m["accuracy_hints"]["red_flags"].values()))
            if row.get("Notes"):
                per_model[name]["notes"].append(f"{brief_id}: {row['Notes']}")

    rows = []
    for name, data in per_model.items():
        criterion_avgs = {c: round(mean(data[c]), 2) for c in RUBRIC if data[c]}
        rows.append(
            {
                "model": name,
                "overall": round(mean(criterion_avgs.values()), 2) if criterion_avgs else None,
                **criterion_avgs,
                "ok_runs": f"{data['status'].count('ok')}/{len(data['status'])}",
                "avg_time_s": round(mean(data["time"])) if data["time"] else None,
                "avg_tok_s": round(mean(data["tps"]), 1) if data["tps"] else None,
                "avg_fkgl_gap": round(mean(data["fkgl_gap"]), 1) if data["fkgl_gap"] else None,
                "red_flags": sum(data["red_flags"]) if data["red_flags"] else 0,
                "notes": "; ".join(data["notes"]),
            }
        )
    rows.sort(key=lambda r: (r["overall"] is None, -(r["overall"] or 0)))
    return rows


def to_markdown(rows, title):
    cols = ["Model", "Overall", *RUBRIC, "OK runs", "Avg time (s)", "tok/s", "FKGL gap", "Red flags"]
    lines = [f"### {title}", "", "| " + " | ".join(cols) + " |", "|---" * len(cols) + "|"]
    for r in rows:
        values = [
            r["model"],
            r["overall"],
            *[r.get(c) for c in RUBRIC],
            r["ok_runs"],
            r["avg_time_s"],
            r["avg_tok_s"],
            r["avg_fkgl_gap"],
            r["red_flags"],
        ]
        lines.append("| " + " | ".join("–" if v is None else str(v) for v in values) + " |")
    notes = [f"- **{r['model']}:** {r['notes']}" for r in rows if r["notes"]]
    if notes:
        lines += ["", "Scorer notes:", "", *notes]
    return "\n".join(lines) + "\n"


def write_into_doc(doc_path, section):
    doc_path = Path(doc_path)
    text = doc_path.read_text(encoding="utf-8")
    if START not in text:
        text = text.rstrip() + f"\n\n{START}\n{END}\n"
    head, rest = text.split(START, 1)
    body, tail = rest.split(END, 1)
    doc_path.write_text(f"{head}{START}\n{body.strip()}\n\n{section}\n{END}{tail}", encoding="utf-8")
