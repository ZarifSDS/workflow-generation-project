"""The vendored skill files match their manifest (apps/quality/vendor_manifest.py)."""

import pytest

from apps.quality import vendor_manifest as manifest


def test_every_vendored_file_is_in_the_manifest_with_its_current_hash():
    recorded = manifest.load()
    assert recorded, (
        "apps/quality/vendor/MANIFEST.json is missing: run python -m apps.quality.vendor_manifest --write"
    )
    current = dict(manifest.vendored_files())
    assert set(current) == set(recorded), "vendored files and the manifest disagree; re-run the manifest"
    changed = [key for key, path in current.items() if manifest.sha256(path) != recorded[key]["sha256"]]
    assert not changed, (
        f"vendored files changed without the manifest: {changed}. Edit the skill and copy the file again "
        "(or mark a deliberate fork in vendor_manifest.FORKS), then re-run the manifest."
    )


@pytest.mark.skipif(not manifest.SKILLS.exists(), reason="the Claude Code skills aren't installed here (CI)")
def test_vendored_copies_are_not_behind_the_skills():
    assert not manifest.drift(), manifest.drift()
