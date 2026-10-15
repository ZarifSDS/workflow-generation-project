"""Vendored skill scripts and the review-and-edit sequence: scan, /deslop, /clarity-review, grade tuning."""

import json

import pytest
from django.core.management import call_command

from apps.quality import house, review, scans, scripts
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

{LONG_SENTENCE} {LONG_SENTENCE} {LONG_SENTENCE} Documentation obligations encompass comprehensive \
organisational accountability considerations.

## Practical policy

Keep the current SDS available on every shift. Archive old versions in one place.
"""
BRIEF = {"fkgl": 9, "region": "US", "pkeyword": "SDS retention requirements", "skeywords": []}


class FakeEditor:
    def __init__(self, break_headings=False, change_fact=False):
        self.calls, self.break_headings, self.change_fact = [], break_headings, change_fact

    def __call__(self, name, context):
        self.calls.append(name)
        if name == "review_wordlevel":
            return context["section"].replace(
                "encompass comprehensive organisational accountability considerations",
                "cover who is responsible",
            )
        if self.break_headings:
            return "Just one paragraph with no headings at all, which drops structure."
        text = context["article"]
        if name == "review_deslop":
            text = text.replace(
                "In this article we will explore SDS retention requirements for employers. ", ""
            )
            if self.change_fact:
                text = text.replace("thirty years", "ten years")
            return text + "\n\n## Deslop notes\n- Practical policy: no specific fact a reader could act on."
        if name == "review_clarity":
            return text.replace(
                "Keep the current sheet on site.", "Keep the current safety data sheet on site."
            ) + ("\n\n## Clarity edits\n- Unresolved referent: intro, “the current sheet” now names the SDS.")
        return text


def test_vendored_metrics_and_scanners_run():
    assert scripts.fkgl(ARTICLE) is not None
    lexical = scripts.run_json(
        "lexical", ARTICLE, "--allow-title-case", "--wordlist", str(review.BANNED_WORDS_TSV)
    )
    assert "slop_index" in lexical
    summary = scans.summary(ARTICLE)
    assert {"slop_index", "unclear_references", "sweep_blocking"} <= set(summary)


def test_clean_text_script_removes_hidden_characters():
    cleaned, _stats = scripts.clean_text("Safe​text here.\n")
    assert "​" not in cleaned and "Safetext" in cleaned


def test_sequence_is_scan_deslop_clarity_tune_rescan():
    editor = FakeEditor()
    outcome = review.run_sequence(ARTICLE, BRIEF, editor)
    assert [s["name"] for s in outcome.substeps] == [
        "Scan",
        "Deslop rewrite",
        "Clarity-review rewrite",
        "Reading grade by section (syntactic unpacking)",
        "Re-scan",
    ]
    assert editor.calls[:2] == ["review_deslop", "review_clarity"]
    assert "In this article" not in outcome.text  # deslop
    assert "the current safety data sheet" in outcome.text  # clarity
    assert "encompass comprehensive" not in outcome.text  # tuned: the section was above target
    assert "## Deslop notes" not in outcome.text and "## Clarity edits" not in outcome.text
    assert outcome.questions == ["Practical policy: no specific fact a reader could act on."]
    assert outcome.clarity_edits and outcome.metrics["before"]["fkgl"] and outcome.metrics["after"]["fkgl"]
    assert outcome.proposals == []  # split proposals are retired


def test_rewrite_that_drops_headings_is_not_used():
    outcome = review.run_sequence(ARTICLE, BRIEF, FakeEditor(break_headings=True))
    assert "## Practical policy" in outcome.text
    deslop = next(s for s in outcome.substeps if s["number"] == 2)
    assert deslop["changed"] is False and "not used" in deslop["summary"]


def test_rewrite_that_changes_a_fact_is_not_used():
    ok, reason = review.protected_ok(
        "Keep it for 30 years under 1910.1020(d).", "Keep it for 10 years under 1910.1020(d)."
    )
    assert not ok and "30 years" in reason


def test_negations_must_survive_but_negative_parallelism_may_unfold():
    assert not review.protected_ok("Employers must not discard it.", "Employers must discard it.")[0]
    assert review.protected_ok("It's not just a form, but a record.", "It's a record.")[0]


def test_grades_skip_references_tables_and_markers():
    text = (
        "# T\n\n## Body\n\n"
        + "Plain words help people read. " * 12
        + "[SRC: https://osha.gov/x]\n\n## References\n\n1. OSHA.\n"
    )
    rows = review.unit_rows(text, 9)
    refs = next(r for r in rows if r["name"] == "References")
    assert refs["graded"] is False and refs["grade"] is None
    assert review.article_metrics(text)["words"] < 80


def test_house_mechanics_and_markers():
    fixed, counts = house.mechanical_fix(
        "A rule — with “quotes” , ranges 10–20.\n\n---\n\n[HERO: drums]\nEnd\\.\n"
    )
    assert "—" not in fixed and '"quotes"' in fixed and "10-20" in fixed and "---" not in fixed
    assert "[HERO" not in fixed and "End." in fixed and counts["dashes"] == 2
    markers = house.find_markers(
        "# T\n\nA fact [VERIFY] [SRC: https://x.y].\n\n## B\n\n[VISUAL: chart, rates]\n"
    )
    assert [m["kind"] for m in markers] == ["VERIFY", "SRC", "VISUAL"] and markers[2]["section"] == "B"
    assert "[SRC" not in house.strip_sources("A fact [SRC: https://x.y].")


@pytest.mark.django_db
def test_legacy_split_proposals_can_still_be_accepted(admin_user):
    brief = ContentBrief.objects.create(
        topic="t",
        pkeyword="SDS retention requirements",
        fkgl=9,
        content_type="seo_blog",
        created_by=admin_user,
    )
    run = services.create_run(brief, {})
    step = run.steps.get(key="review_edit")
    proposal = {
        "id": "abc12345",
        "section": "How long",
        "original": LONG_SENTENCE,
        "split": SPLIT,
        "before": 20,
        "after": 12,
    }
    services.add_version(
        step, ARTICLE, extra_metrics={"review": {"substeps": [], "grades": [], "proposals": [proposal]}}
    )
    step.status = StepRun.Status.READY
    step.save()
    version = services.accept_splits(step, admin_user, ["abc12345"])
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


def test_a_refused_section_reverts_alone_and_the_other_edits_stay():
    # One changed fact used to throw away the whole deslop pass (docs/sop-audit.md).
    outcome = review.run_sequence(ARTICLE, BRIEF, FakeEditor(change_fact=True))
    assert "In this article" not in outcome.text  # the intro's edit is kept
    assert "thirty years" in outcome.text and "ten years" not in outcome.text  # the fact's section reverted
    assert any("kept as they were" in note for note in outcome.questions)


def test_a_number_protects_its_unit_not_the_next_word():
    assert review.protected_ok(
        "Section 1910.1200 requires training.", "Under Section 1910.1200, employers must train workers."
    )[0]
    assert review.protected_ok("Workers in 2024 reported it.", "In 2024, workers reported it.")[0]
    assert not review.protected_ok("Keep it for 30 years.", "Keep it for 30 months.")[0]
    assert not review.protected_ok("Limit exposure to 50 ppm.", "Limit exposure to 5 ppm.")[0]


# ---- Phase 7 (docs/sop-audit.md): grade tuning ----


def test_grading_leaves_headings_out_and_ends_list_items():
    text = (
        "## Steps for Reading the Hazard Section of a Safety Data Sheet\n\nRead section two first. "
        "It lists the hazards you need before you open the container.\n\n- Signal word\n"
        "- Pictograms and hazard statements\n- Precautionary statements for handling\n- Supplier contact details\n"
    ) * 4  # a grade needs 100 words
    graded = review.grading_text(text)
    assert "Steps for Reading" not in graded  # a heading isn't part of a sentence
    assert "- Signal word.\n" in graded and "- Supplier contact details.\n" in graded
    punctuated = text.replace("word\n", "word.\n").replace("statements\n", "statements.\n")
    punctuated = punctuated.replace("handling\n", "handling.\n").replace("details\n", "details.\n")
    assert review.grade(text) == review.grade(punctuated)  # the list reads as its items
    m = scripts.metrics_module()  # the previous reading: heading joined, list run on
    old = m.fkgl(m.split_sentences(m.strip_markdown(review.prose(text))))[0]
    assert review.grade(text) < old


def test_the_vocabulary_floor_keeps_short_dense_sentences_untuned():
    dense = "Organisational accountability necessitates comprehensive documentation procedures. " * 20
    floor = review.vocabulary_floor(dense)
    assert floor and review.grade(dense) <= floor + 1  # its sentences are short: only words lift the grade
    stacked = (
        "Employers that keep chemicals on site must make the safety data sheet available to every worker on "
        "every shift, which means keeping a copy where the work happens and replacing it when the supplier "
        "sends a new version. "
    ) * 4
    assert review.grade(stacked) > review.vocabulary_floor(stacked) + 1  # long sentences: unpacking helps
    assert review.stacked_sentences(stacked)


def test_tuning_that_repeats_the_subject_down_a_paragraph_is_refused():
    section = (
        "## Storage\n\nEmployers that keep chemicals on site must make the safety data sheet available to every "
        "worker on every shift, which means keeping a copy where the work happens and replacing it when the "
        "supplier sends a new version of the sheet.\n"
    )
    choppy = (
        "## Storage\n\nThe employer keeps chemicals on site. The employer makes the sheet available. The employer "
        "keeps a copy where the work happens. The employer replaces it when the supplier sends a new version of "
        "the safety data sheet to every worker on every shift.\n"
    )
    assert review.opener_run(choppy) == 4 and review.opener_run(section) == 1

    def call(name, ctx):
        assert "which means keeping a copy" in ctx["stacked"]
        return choppy

    with pytest.raises(ValueError, match="same subject"):
        review.tune_unit(section, 1, 9, "US", call)


def test_structural_scan_findings_reach_the_report_not_the_rewrite():
    findings = review._deslop_findings(
        {
            "findings": [
                {
                    "id": "banned-A:utilize",
                    "severity": "medium",
                    "count": 2,
                    "examples": [{"text": "utilize"}],
                    "fix": "Use 'use' unless the condition applies.",
                },
                {"id": "curly-quotes", "severity": "low", "count": 3},
            ]
        },
        {"findings": [{"id": "flat-sentence-rhythm", "value": 0.2, "fix": "Vary it."}]},
        {},
    )
    assert any("banned-A:utilize" in f and "→ Use 'use'" in f for f in findings)
    assert not any("curly-quotes" in f or "flat-sentence" in f for f in findings)
    assert review._structure_notes({"findings": [{"id": "flat-sentence-rhythm", "value": 0.2}]}) == [
        "flat-sentence-rhythm=0.2"
    ]
    candidates = review._clarity_candidates({"term_drift": {"SDS": 9, "safety data sheet": 4, "MSDS": 0}})
    assert any("SDS ×9" in c and "safety data sheet ×4" in c for c in candidates)
