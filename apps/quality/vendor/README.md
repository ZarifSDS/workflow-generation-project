# Vendored skill scripts

Copied unchanged from the author's Claude Code skills (`~/.claude/skills/`) on 2026-10-13, so the
Content Studio's checks behave exactly like the manual workflow. Do not edit these files here:
update the skill, then copy the file again.

| Folder | Skill | Scripts |
|---|---|---|
| `deslop/` | deslop | `lexical_scan.py`, `structure_scan.py`, `redundancy_scan.py` |
| `clarity_review/` | clarity-review | `frame_scan.py` |
| `sds_hero_stock/` | sds-hero-stock | `hero_compose.py`, `reframe.py`, `check_photo.py`, `overlay.py`, `inner_logo.py` and helpers (brand assets git-ignored) |
| `clean_user_facing_text/` | clean-user-facing-text | `clean_text.py`, `inspect_text.py`, `text_unicode.py`, `common.py`, `score_stylometry.py` |
| `ehs_seo_blog/` | ehs-seo-blog-optimized | `metrics.py`, `prose_signals.py`, `mechanical_sweep.py`, `link_check.py` and `editorial_flow_check.py` (added 2026-10-14; the SOP's article checks run both), `data/banned-words.json`, `data/banned-words.tsv`, `data/internal-article-links.md` (published rows only: the planned-slugs section is removed because the repo is public), `data/product-link-registry.json` (data added 2026-10-14) |

They are standard-library Python and are run through their `--json` command-line interfaces
(`apps/quality/scripts.py`), except `metrics.py`, whose grade functions are imported directly so the
per-section grades use the same formula as the skill.
