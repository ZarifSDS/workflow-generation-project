"""Run the vendored skill scripts (apps/quality/vendor) through their --json interfaces."""

import importlib.util
import json
import subprocess
import sys
import tempfile
from functools import cache
from pathlib import Path

VENDOR = Path(__file__).parent / "vendor"

SCRIPTS = {
    "lexical": VENDOR / "deslop/scripts/lexical_scan.py",
    "structure": VENDOR / "deslop/scripts/structure_scan.py",
    "redundancy": VENDOR / "deslop/scripts/redundancy_scan.py",
    "frames": VENDOR / "clarity_review/scripts/frame_scan.py",
    "unicode": VENDOR / "clean_user_facing_text/scripts/inspect_text.py",
    "clean": VENDOR / "clean_user_facing_text/scripts/clean_text.py",
    "metrics": VENDOR / "ehs_seo_blog/scripts/metrics.py",
    "prose": VENDOR / "ehs_seo_blog/scripts/prose_signals.py",
    "sweep": VENDOR / "ehs_seo_blog/scripts/mechanical_sweep.py",
}


class ScriptError(Exception):
    pass


def _run(name, text, args=(), timeout=60):
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as handle:
        handle.write(text)
        path = handle.name
    try:
        return subprocess.run(
            [sys.executable, str(SCRIPTS[name]), path, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
        )
    finally:
        Path(path).unlink(missing_ok=True)


def run_json(name, text, *args):
    """Run a scanner with --json and return its parsed output."""
    result = _run(name, text, (*args, "--json"))
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise ScriptError(f"{name} returned no JSON: {(result.stderr or result.stdout)[:300]}") from error


def clean_text(text):
    """clean_text.py: returns (cleaned text, stats dict).

    Given a file path, the script writes to `<name>.cleaned.<ext>` unless `-o` is set, so an explicit
    output file is passed and read back.
    """
    with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as handle:
        out_path = Path(handle.name)
    try:
        result = _run("clean", text, ("-o", str(out_path), "--stats"))
        if result.returncode != 0:
            raise ScriptError(f"clean_text failed: {result.stderr[:300]}")
        cleaned = out_path.read_text(encoding="utf-8")
    finally:
        out_path.unlink(missing_ok=True)
    try:
        stats = json.loads(result.stderr) if result.stderr.strip().startswith("{") else {}
    except json.JSONDecodeError:
        stats = {}
    return cleaned, stats


@cache
def metrics_module():
    """The skill's metrics.py, imported so grades use exactly the skill's formula."""
    spec = importlib.util.spec_from_file_location("ehs_metrics", SCRIPTS["metrics"])
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fkgl(text):
    """FKGL with the skill's own syllable heuristic; None for very short text."""
    m = metrics_module()
    grade, words, _sentences = m.fkgl(m.split_sentences(m.strip_markdown(text)))
    return round(grade, 1) if words >= 30 else None
