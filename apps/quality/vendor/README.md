# Vendored skill scripts

Copied unchanged from the author's Claude Code skills (`~/.claude/skills/`) on 2026-10-13, so the
Content Studio's checks behave exactly like the manual workflow. Do not edit these files here:
update the skill, then copy the file again.

| Folder | Skill | Scripts |
|---|---|---|
| `deslop/` | deslop | `lexical_scan.py`, `structure_scan.py`, `redundancy_scan.py` |
| `clarity_review/` | clarity-review | `frame_scan.py` |
| `clean_user_facing_text/` | clean-user-facing-text | `clean_text.py`, `inspect_text.py`, `text_unicode.py`, `common.py`, `score_stylometry.py` |
| `ehs_seo_blog/` | ehs-seo-blog-optimized | `metrics.py`, `prose_signals.py`, `mechanical_sweep.py`, `data/banned-words.json` |

They are standard-library Python and are run through their `--json` command-line interfaces
(`apps/quality/scripts.py`), except `metrics.py`, whose grade functions are imported directly so the
per-section grades use the same formula as the skill.
