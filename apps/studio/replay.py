"""Offline replay of the SOP's deterministic checks: no model calls.

Runs `sop.normalise` and `sop.check` (exactly what the loop does before the reviewer) over stored step
versions or fixture texts, and summarises which checks fire, how often, and on what text. It is the
measuring instrument for the SOP audit (docs/sop-audit.md, phase 1): a change to a check shows its
false-positive and catch counts on real runs and on the fixtures before any live run.

    python manage.py sop_replay                      # every stored text version
    python manage.py sop_replay --runs 19 20 21 --latest --out var/replay.md
"""

from collections import defaultdict
from dataclasses import dataclass, field

from . import sop


@dataclass
class Row:
    """One replayed text: where it came from and what the checks said."""

    label: str
    step_key: str
    findings: list = field(default_factory=list)
    fixes: dict = field(default_factory=dict)

    @property
    def blocks(self):
        return [f for f in self.findings if f.severity == "block"]


def findings_for(step_key, text, ctx):
    """(normalised text, fixes, findings) for one text, as the loop would see it before the reviewer."""
    normalised, fixes = sop.normalise(step_key, text)
    return normalised, fixes, sop.check(step_key, normalised, ctx)


def replay_versions(versions):
    """Rows for StepVersions (any iterable); steps without SOP checks are skipped."""
    rows = []
    contexts = {}
    for version in versions:
        step = version.step
        if step.key not in sop.CHECKS or not (version.content or "").strip():
            continue
        if step.pk not in contexts:
            contexts[step.pk] = sop.context_from(step)
        _, fixes, found = findings_for(step.key, version.content, contexts[step.pk])
        rows.append(Row(f"run {step.run_id} {step.key} v{version.number}", step.key, found, fixes))
    return rows


def summarise(rows):
    """{(severity, kind): {"count", "texts": set of labels, "examples": [(label, finding text)]}}."""
    summary = defaultdict(lambda: {"count": 0, "texts": set(), "examples": []})
    for row in rows:
        for finding in row.findings:
            entry = summary[(finding.severity, sop.check_kind(finding))]
            entry["count"] += 1
            entry["texts"].add(row.label)
            if len(entry["examples"]) < 3:
                entry["examples"].append((row.label, finding.text))
    return summary


def to_markdown(rows, title="SOP check replay"):
    summary = summarise(rows)
    order = {"block": 0, "advise": 1, "note": 2}
    lines = [
        f"# {title}",
        "",
        f"{len(rows)} texts replayed; {sum(len(r.blocks) for r in rows)} blocking findings, "
        f"{sum(not r.blocks for r in rows)} texts with none.",
        "",
        "## Findings by check",
        "",
        "| Severity | Check | Firings | Texts |",
        "|---|---|---|---|",
    ]
    ranked = sorted(summary.items(), key=lambda item: (order.get(item[0][0], 3), -item[1]["count"]))
    for (severity, kind), entry in ranked:
        lines.append(f"| {severity} | {kind.replace('|', '/')} | {entry['count']} | {len(entry['texts'])} |")
    lines += ["", "## Examples (read each: is it a real defect?)", ""]
    for (severity, kind), entry in ranked:
        if severity == "note":
            continue
        lines.append(f"### [{severity}] {kind}")
        lines.append("")
        for label, text in entry["examples"]:
            lines.append(f"- {label}: {text[:300]}")
        lines.append("")
    lines += ["## Per text", "", "| Text | Blocks | Advisories | Auto-fixed |", "|---|---|---|---|"]
    for row in rows:
        advise = sum(f.severity == "advise" for f in row.findings)
        fixed = ", ".join(f"{k}: {n}" for k, n in row.fixes.items()) or "-"
        lines.append(f"| {row.label} | {len(row.blocks)} | {advise} | {fixed} |")
    return "\n".join(lines) + "\n"
