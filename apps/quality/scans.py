"""Quality summary for a piece of text, built from the vendored skill scanners."""

import logging

from . import scripts

logger = logging.getLogger(__name__)


def _safe(name, text, *args):
    try:
        return scripts.run_json(name, text, *args)
    except (scripts.ScriptError, OSError, TimeoutError) as error:
        logger.warning("Quality scan %s failed: %s", name, error)
        return None


def summary(text):
    """Compact numbers for the checks panel; full findings are kept for the review sequence."""
    lexical = _safe("lexical", text) or {}
    structure = _safe("structure", text) or {}
    frames = _safe("frames", text) or {}
    sweep = _safe("sweep", text) or {}
    unicode = _safe("unicode", text) or {}
    return {
        "slop_index": lexical.get("slop_index"),
        "deslop_findings": [
            {
                "id": f.get("id"),
                "severity": f.get("severity"),
                "count": f.get("count"),
                "examples": [e.get("text") for e in (f.get("examples") or [])[:3]],
            }
            for f in lexical.get("findings", [])
        ],
        "sentence_len_cv": structure.get("sentence_len_cv"),
        "sentence_len_band": structure.get("sentence_len_band"),
        "frames_over_threshold": len(frames.get("frames_over_threshold", []) or []),
        "unclear_references": len(frames.get("bare_demonstratives", []) or []),
        "placeholder_nouns": len(frames.get("placeholder_nouns", []) or []),
        "sweep_blocking": sweep.get("blocking_count"),
        "hidden_characters": unicode.get("suspicious_total"),
    }
