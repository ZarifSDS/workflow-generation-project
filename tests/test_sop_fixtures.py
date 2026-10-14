"""Fixture A / Fixture B calibration of the SOP's deterministic checks (tests/fixtures/sop/README.md).

No model calls: each fixture goes through `replay.findings_for`, the normalisation and checks the loop runs
before its reviewer, and through the edit step's lexical scan for Fixture B's `scans`.
"""

from pathlib import Path

import pytest
import yaml

from apps.quality import review
from apps.studio import replay

FIXTURES = Path(__file__).parent / "fixtures" / "sop"


def load(path):
    raw = path.read_text(encoding="utf-8")
    _, front, body = raw.split("---\n", 2)
    meta = yaml.safe_load(front) or {}
    ctx = {
        "pkeyword": meta.get("pkeyword", ""),
        "skeywords": meta.get("skeywords", []),
        "content_type": meta.get("content_type", "seo_blog"),
        "region": meta.get("region", "US"),
        "wordcount": meta.get("wordcount"),
        "fkgl": float(meta.get("fkgl", 9)),
        "cta_style": meta.get("cta_style", "subtle"),
        "anchors": meta.get("anchors", []),
        "metadata_counts": {},
        "allowed_urls": set(meta["allowed_urls"]) if "allowed_urls" in meta else None,
        "allowed_citations": set(meta["allowed_citations"]) if "allowed_citations" in meta else None,
    }
    return meta, body, ctx


def fixtures(folder):
    return sorted((FIXTURES / folder).glob("*.md"))


def _fired(findings, severity="block"):
    return [f.text for f in findings if f.severity == severity]


@pytest.mark.parametrize("path", fixtures("b"), ids=lambda p: p.stem)
def test_fixture_b_every_planted_defect_is_caught(path):
    meta, body, ctx = load(path)
    _, _, findings = replay.findings_for(meta["step"], body, ctx)
    fired = _fired(findings)
    missed = [check for check in meta.get("checks", []) if not any(check in text for text in fired)]
    assert not missed, f"planted defects not caught: {missed}"
    declared = [*meta.get("checks", []), *meta.get("also_fires", [])]
    unexpected = [text for text in fired if not any(item in text for item in declared)]
    assert not unexpected, (
        f"blocks this fixture doesn't declare (a new check or a false positive): {unexpected}"
    )
    if meta.get("scans"):
        ids = {f.get("id") for f in review._lexical(body).get("findings", [])}
        assert not set(meta["scans"]) - ids, f"scans that didn't flag: {set(meta['scans']) - ids}"
    for gap in meta.get("known_gaps", []):
        print(f"known gap ({path.stem}): {gap}")


def test_fixture_a_approved_articles_raise_no_blocks():
    paths = fixtures("a")
    if not paths:
        pytest.skip("No Fixture A article yet: add an owner-approved article to tests/fixtures/sop/a/")
    failures = {}
    for path in paths:
        meta, body, ctx = load(path)
        _, _, findings = replay.findings_for(meta["step"], body, ctx)
        accepted = meta.get("accepted_blocks", [])
        blocks = [t for t in _fired(findings) if not any(a in t for a in accepted)]
        if blocks:
            failures[path.stem] = blocks
    assert not failures, f"approved articles tripped blocking checks (false positives): {failures}"


def test_the_replay_summarises_by_check(tmp_path):
    meta, body, ctx = load(fixtures("b")[0])
    _, fixes, findings = replay.findings_for(meta["step"], body, ctx)
    row = replay.Row("fixture b", meta["step"], findings, fixes)
    report = replay.to_markdown([row])
    assert "| block | the heading '…' joins a topic and its qualifier with a comma" in report
    assert "fixture b" in report
