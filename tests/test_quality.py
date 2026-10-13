"""M5: vendored skill scripts and the review-and-edit sequence."""

import json

import pytest
from django.core.management import call_command

from apps.quality import review, scans, scripts
from apps.studio import services
from apps.studio.models import ContentBrief, StepRun

LONG_SENTENCE = (
    "Employers that discontinue a hazardous chemical may discard its safety data sheet only when they keep a "
    "record of the chemical's identity, the location where it was used and the period of use for at least "
    "thirty years under the access to employee exposure and medical records standard."
)
SPLIT = (
    "Employers that stop using a hazardous chemical may discard its safety data sheet. They must keep a record "
    "of the chemical's identity, where it was used and when. That record must be kept for at least thirty years "
    "under the access to employee exposure and medical records standard."
)
ARTICLE = f"""# SDS retention requirements

In this article we will explore SDS retention requirements for employers. Keep the current sheet on site.

## How long to keep safety data sheets

{LONG_SENTENCE} Documentation obligations encompass comprehensive organisational accountability considerations.

## Practical policy

Keep the current SDS available on every shift. Archive old versions in one place.
"""
BRIEF = {"fkgl": 9, "region": "US", "pkeyword": "SDS retention requirements"}


class FakeEditor:
    def __init__(self, break_headings=False):
        self.calls, self.break_headings = [], break_headings

    def __call__(self, name, context):
        self.calls.append(name)
        if name == "review_splits":
            return json.dumps([{"n": 1, "split": SPLIT}])
        if name == "review_wordlevel":
            return context["section"].replace(
                "encompass comprehensive organisational accountability considerations",
                "cover who is responsible",
            )
        if self.break_headings:
            return "Just one paragraph with no headings at all, which drops structure."
        return context["article"].replace(
            "In this article we will explore SDS retention requirements for employers. ", ""
        )


def test_vendored_metrics_and_scanners_run():
    assert scripts.fkgl(ARTICLE) is not None
    lexical = scripts.run_json("lexical", ARTICLE)
    assert "slop_index" in lexical
    summary = scans.summary(ARTICLE)
    assert {"slop_index", "unclear_references", "sweep_blocking"} <= set(summary)


def test_clean_text_script_removes_hidden_characters():
    cleaned, _stats = scripts.clean_text("Safe​text here.\n")
    assert "​" not in cleaned and "Safetext" in cleaned


def test_sequence_runs_all_seven_substeps_and_only_proposes_splits():
    editor = FakeEditor()
    outcome = review.run_sequence(ARTICLE, BRIEF, editor)
    assert [s["number"] for s in outcome.substeps] == [1, 2, 3, 4, 5, 6, 7]
    assert "In this article" not in outcome.text
    assert "encompass comprehensive" not in outcome.text  # word-level edit applied (section above grade 13)
    assert LONG_SENTENCE in outcome.text  # the split is NOT applied automatically
    assert outcome.proposals and outcome.proposals[0]["before"] - outcome.proposals[0]["after"] >= 1.0
    applied = review.apply_splits(outcome.text, outcome.proposals, {outcome.proposals[0]["id"]})
    assert SPLIT in applied and LONG_SENTENCE not in applied


def test_rewrite_that_drops_headings_is_not_used():
    outcome = review.run_sequence(ARTICLE, BRIEF, FakeEditor(break_headings=True))
    assert "## Practical policy" in outcome.text
    meta = next(s for s in outcome.substeps if s["number"] == 4)
    assert meta["changed"] is False and "not used" in meta["summary"]


@pytest.mark.django_db
def test_accept_splits_creates_your_edit_version(admin_user):
    brief = ContentBrief.objects.create(
        topic="t",
        pkeyword="SDS retention requirements",
        fkgl=9,
        content_type="seo_blog",
        created_by=admin_user,
    )
    run = services.create_run(brief, {})
    step = run.steps.get(key="review_edit")
    outcome = review.run_sequence(ARTICLE, BRIEF, FakeEditor())
    services.add_version(
        step,
        outcome.text,
        extra_metrics={
            "review": {"substeps": outcome.substeps, "grades": outcome.grades, "proposals": outcome.proposals}
        },
    )
    step.status = StepRun.Status.READY
    step.save()
    version = services.accept_splits(step, admin_user, [outcome.proposals[0]["id"]])
    assert version.source == "edit" and SPLIT in version.content
    assert version.metrics["review"]["proposals"] == [] and len(version.metrics["review"]["accepted"]) == 1


@pytest.mark.django_db
def test_edit_round_dry_run(tmp_path):
    drafts = tmp_path / "drafts"
    drafts.mkdir()
    (drafts / "b1-sds-retention.md").write_text(ARTICLE, encoding="utf-8")
    run_dir = tmp_path / "run"
    call_command(
        "eval_models",
        "--round",
        "edit",
        "--run-dir",
        str(run_dir),
        "--dry-run",
        "--seed",
        "1",
        "--only-briefs",
        "b1-sds-retention",
        "--models",
        "gpt-oss:120b",
        "--drafts-dir",
        str(drafts),
    )
    results = json.loads((run_dir / "results.json").read_text())
    record = next(iter(results["b1-sds-retention"].values()))
    assert record["status"] == "ok" and record["calls"] >= 2
    assert "Review sequence report" in (run_dir / record["file"]).read_text()
