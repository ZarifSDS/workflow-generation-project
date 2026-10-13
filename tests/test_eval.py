import json
from pathlib import Path

from django.core.management import call_command

from apps.ai.evaluation import metrics, report
from apps.ai.evaluation.runner import assign_labels, load_yaml, render_messages

ROOT = Path(__file__).resolve().parent.parent
BRIEF = {
    "id": "b-test",
    "type": "outbound",
    "topic": "Secondary container labelling",
    "pkeyword": "secondary container labelling",
    "skeywords": ["workplace chemical labels"],
    "wordcount": 100,
    "fkgl": 8,
    "region": "UK",
    "site": "A UK blog",
    "narrative_mode": "informational",
    "checks": {"good": ["COSHH"], "red_flags": ["OSHA"]},
}


def test_metrics_keyword_spelling_and_flags():
    text = (
        "# Secondary container labelling basics\n\n"
        "Secondary container labelling keeps workers safe under COSHH. In this article we explain "
        "workplace chemical labels and why labeling matters for every organization that decants chemicals "
        "into smaller bottles for daily tasks on site.\n\n"
        "## Why OSHA rules don't apply\n\nThey are US rules.\n"
    )
    result = metrics.compute(text, BRIEF)
    assert result["pkeyword"]["in_h1"] and result["pkeyword"]["in_first_100_words"]
    assert result["skeywords"] == {"workplace chemical labels": 1}
    assert result["wrong_spelling_variant"] == {"labeling": 1, "organization": 1}
    assert result["accuracy_hints"]["good"]["COSHH"] == 1
    assert result["accuracy_hints"]["red_flags"]["OSHA"] == 1
    assert result["meta_narration"] == 1
    assert [s["heading"] for s in result["section_fkgl"]] == ["(intro)", "Why OSHA rules don't apply"]


def test_render_messages_fills_brief_and_type():
    types = load_yaml(ROOT / "eval" / "prompts" / "types.yaml")
    messages = render_messages(ROOT / "eval" / "prompts" / "outline.md", BRIEF, types)
    assert messages[0]["role"] == "system" and "Never invent" in messages[0]["content"]
    user = messages[1]["content"]
    assert (
        "secondary container labelling" in user
        and "Guest post" in user
        and "| Target site | A UK blog |" in user
    )
    assert "{{" not in user


def test_labels_are_shuffled_per_brief_but_reproducible():
    candidates = [{"provider": "p", "model": str(i)} for i in range(6)]
    first = assign_labels(["a", "b"], candidates, seed=7)
    assert first == assign_labels(["a", "b"], candidates, seed=7)
    assert sorted(first["a"]) == list("ABCDEF")
    assert sorted(c["model"] for c in first["a"].values()) == [str(i) for i in range(6)]


def test_dry_run_round_and_report(tmp_path):
    run_dir = tmp_path / "run"
    call_command(
        "eval_models",
        "--round",
        "outline",
        "--run-dir",
        str(run_dir),
        "--dry-run",
        "--seed",
        "1",
        "--only-briefs",
        "b1-sds-retention",
        "--models",
        "gpt-oss",
    )
    key = json.loads((run_dir / "key.json").read_text())
    results = json.loads((run_dir / "results.json").read_text())
    labels = sorted(key["b1-sds-retention"])
    assert labels == ["A", "B"]
    assert all(results["b1-sds-retention"][label]["status"] == "ok" for label in labels)
    assert (run_dir / "outputs" / "b1-sds-retention" / "A.md").exists()

    scorecard = (run_dir / "scorecard.md").read_text()
    scorecard = scorecard.replace("| A |  |  |  |  |  |  |", "| A | 5 | 4 | 4 | 3 | 4 | solid |")
    scorecard = scorecard.replace("| B |  |  |  |  |  |  |", "| B | 2 | 3 | 3 | 3 | 2 |  |")
    (run_dir / "scorecard.md").write_text(scorecard)

    rows = report.summarise(run_dir)
    assert rows[0]["overall"] == 4.0 and rows[0]["model"] == "{provider}/{model}".format(
        **key["b1-sds-retention"]["A"]
    )
    doc = tmp_path / "model-eval.md"
    doc.write_text("# Model evaluation\n")
    report.write_into_doc(doc, report.to_markdown(rows, "Run test"))
    assert "### Run test" in doc.read_text() and report.START in doc.read_text()


def test_run_can_be_extended_with_new_candidates(tmp_path, settings):
    run_dir = tmp_path / "run"
    base = [
        "--round",
        "outline",
        "--run-dir",
        str(run_dir),
        "--dry-run",
        "--seed",
        "3",
        "--only-briefs",
        "b1-sds-retention",
    ]
    call_command("eval_models", *base, "--models", "gpt-oss:120b")
    first = json.loads((run_dir / "key.json").read_text())["b1-sds-retention"]
    assert sorted(first) == ["A"]

    call_command("eval_models", *base, "--models", "gpt-oss:120b,gemma4")
    key = json.loads((run_dir / "key.json").read_text())["b1-sds-retention"]
    assert key["A"] == first["A"]  # existing label kept
    assert sorted(key) == ["A", "B"]
    scorecard = (run_dir / "scorecard.md").read_text()
    assert "| A |" in scorecard and "| B |" in scorecard
