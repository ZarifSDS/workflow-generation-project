"""The SOP self-review (apps/studio/sop.py, docs/sop.md): deterministic checks, the review-revise loop,
autopilot runs and the UI around them. No real provider calls."""

import re

import pytest
from django.conf import settings
from django.urls import reverse

from apps.ai.types import GenerationResult, ProviderError
from apps.studio import executors, forms, services, sop
from apps.studio.models import ContentBrief, StepRun
from apps.studio.tasks import execute_step

pytestmark = pytest.mark.django_db

GOOD_RESEARCH = """## Search Intent
Informational; the searcher wants to know how long to keep SDSs. Explainer, median 1,400 words.

## What Ranks
Pages frame the title as a question.

## Must Include
- The 30-year rule, because every page covers it.

## Missing Opportunity
- A worked retention schedule.

## Keyword Table
| Keyword | Type | Intent | Planned placement |
|---|---|---|---|
| SDS retention requirements | primary | informational | H1, intro |
| how long to keep safety data sheets | secondary | informational | H2 |
| SDS archive | related | informational | body |

## Regulation Depth
- 29 CFR 1910.1020(d)(1)(ii): the 30-year record rule, because every ranking page cites it.

## Anchor Opportunities
| Target page | Suggested anchor text | Target section | Priority |
|---|---|---|---|
| https://sdsmanager.com/us/ehs-software/ | SDS management software | conclusion | high |

## Questions Searchers Ask
1. How long do you keep SDS? (body)
2. Do I need to keep old SDS? (body)
3. What is the 30-year rule? (body)
4. Can SDS be stored electronically? (FAQ)
5. Who is responsible for SDS? (FAQ)
6. What happens when a product is discontinued? (body)
7. Do SDS expire? (FAQ)
8. How often to update SDS? (FAQ)

## Sources
- Tier 1: OSHA 29 CFR 1910.1020, for the record rule.

## Claims
1. Exposure records are kept for 30 years; 29 CFR 1910.1020; primary read.
2. The HazCom standard requires SDS access on each shift; 29 CFR 1910.1200(g)(8); primary read.
3. Electronic storage is allowed; OSHA letter of interpretation; secondary only [VERIFY].

## Common Misconceptions
- That SDSs must be kept forever.

## Cannibalization
No overlap.

## Questions for the Requester
None.
"""

GOOD_DRAFT = """# SDS Retention Requirements: How Long to Keep Safety Data Sheets

A site manager finds a drum of a solvent the company stopped buying in 2014 and no record of what was in
it. SDS retention requirements decide whether that record still exists. OSHA treats a safety data sheet as
an exposure record, so you keep some record of the product for 30 years. That rule protects workers who get
ill long after a job ends. In this article, you'll learn what to keep, for how long, and how to store it.

## Key Takeaways

- SDS retention requirements come from OSHA's exposure records rule, 29 CFR 1910.1020.
- An employer keeps a record of every hazardous chemical used for 30 years.
- A current safety data sheet must stay available on every shift.

## What Are the SDS Retention Requirements Under OSHA?

You keep a record for 30 years [SRC: https://www.osha.gov/laws-regs]. The record can be the SDS itself or
a list of the product, where it was used and when.

## What Counts as an Exposure Record?

An exposure record is any document that identifies a chemical and where it was used. The [SDS management
guide](https://sdsmanager.com/us/sds-management-articles/sds-guide/) lists the record categories OSHA names.

## Do Safety Data Sheets Expire?

Safety data sheets don't expire, but suppliers revise them. Keep the version in use at the time of exposure.

## Keep Every SDS Where Your Auditor Can Find It

Paper binders go missing when a site closes. This week, list every product in use and the date its SDS
was filed. [SDS Manager's SDS management software](https://sdsmanager.com/us/ehs-software/) keeps the
archive and the dates in one place.

## Frequently Asked Questions

:::faq
### Can Safety Data Sheets Be Stored Electronically?

Safety data sheets can be stored electronically as long as workers can reach them on every shift.

### Who Is Responsible for SDS Retention?

The employer is responsible for SDS retention, even when a supplier hosts the sheets.

### Do You Need to Keep an SDS for a Discontinued Product?

An SDS for a discontinued product stays in the archive for 30 years after the last use.
:::

## References

1. OSHA, 29 CFR 1910.1020. https://www.osha.gov/laws-regs
"""

GOOD_OUTLINE = """## Search Intent
Informational explainer, 1,400 words against a 1,300 median.

## H1 Options
1. SDS Retention Requirements: How Long to Keep Safety Data Sheets (recommended)
2. How Long Should You Keep Safety Data Sheets?

## Detailed Outline
Intro: the pain point.
H2: How Long Do You Keep Safety Data Sheets?
- the 30-year rule
H2: What Counts as an Exposure Record?
H2: Do Safety Data Sheets Expire?
H2: Keep Every SDS Where Your Auditor Can Find It

## Intro Plan
A generic example, why it matters, the snippet, the "this article" promise.

## Conclusion Plan
Gap: binders go missing. Action: list products. Product: https://sdsmanager.com/us/ehs-software/.

## FAQ Plan
1. Can SDS be stored electronically?
2. Who is responsible?
3. Discontinued products?

## Claim Verification Table
| Claim | Source | Status |
|---|---|---|
| 30 years | 29 CFR 1910.1020 | primary read |

## Keyword and Anchor Map
| Keyword or anchor | Kind | Section |
|---|---|---|
| SDS retention requirements | primary | H1 |

## Structure Decisions
- One H2 per searcher question; alternative: merge, rejected.

## Headings-Only Outline
H1: SDS Retention Requirements: How Long to Keep Safety Data Sheets
H2: Key Takeaways
H2: How Long Do You Keep Safety Data Sheets?
H2: What Counts as an Exposure Record?
H2: Do Safety Data Sheets Expire?
H2: Keep Every SDS Where Your Auditor Can Find It
H2: Frequently Asked Questions
H3: Can Safety Data Sheets Be Stored Electronically?
H3: Who Is Responsible for SDS Retention?
H3: Do You Need to Keep an SDS for a Discontinued Product?
"""

CTX = {"pkeyword": "SDS retention requirements", "content_type": "seo_blog", "wordcount": None}


def blocking(findings):
    return [f.text for f in findings if f.severity == "block"]


# ---- Deterministic checks ----


def test_good_outputs_pass_the_checks():
    assert blocking(sop.check("research", GOOD_RESEARCH, CTX)) == []
    assert blocking(sop.check("outline", GOOD_OUTLINE, CTX)) == []
    assert blocking(sop.check("draft", GOOD_DRAFT, CTX)) == []


def test_research_checks_catch_missing_sections_and_keyword():
    text = GOOD_RESEARCH.replace("## Regulation Depth", "## Rules").replace(
        "SDS retention requirements", "retention"
    )
    found = blocking(sop.check("research", text, CTX))
    assert any("missing section(s): Regulation Depth" in f for f in found)
    assert any("primary keyword" in f for f in found)


def test_outline_checks_shape_of_the_headings_only_outline():
    text = GOOD_OUTLINE.replace(
        "H2: Keep Every SDS Where Your Auditor Can Find It\nH2: Frequently", "H2: Conclusion\nH2: Frequently"
    )
    found = blocking(sop.check("outline", text, CTX))
    assert any("generic" in f for f in found)
    text = GOOD_OUTLINE.replace("H2: Key Takeaways\n", "")
    assert any("Key Takeaways" in f for f in blocking(sop.check("outline", text, CTX)))
    text = GOOD_OUTLINE.replace("H3: Do You Need to Keep an SDS for a Discontinued Product?\n", "")
    # Advisory, as in the article: the approved JSA article (Fixture A) has eight.
    found = [str(f) for f in sop.check("outline", text, CTX)]
    assert any("FAQ question" in f and f.startswith("[advise]") for f in found)


def test_draft_checks_catch_the_recurring_misses():
    text = (
        GOOD_DRAFT.replace("In this article, you'll learn", "You will learn")
        .replace("- A current safety data sheet", "- That sheet")
        .replace("Keep Every SDS Where Your Auditor Can Find It", "Conclusion")
        .replace("Safety data sheets can be stored electronically", "Yes, they can be stored electronically")
        .replace("30 years [SRC:", "30 years – the rule [SRC:")
    )
    found = blocking(sop.check("draft", text, CTX))
    joined = " | ".join(found)
    assert "this article" in joined
    assert "leans on another bullet" in joined
    assert "generic" in joined
    assert "bare Yes/No" in joined
    assert "dash" in joined


def test_draft_checks_adjacent_anchors_and_brief_anchors():
    text = GOOD_DRAFT.replace(
        "Keep the version in use at the time of exposure.",
        "Keep the version in use at the time of exposure, see [the archive](https://sdsmanager.com/us/x/).",
    )
    # A guest-post rule: approved blogs (Fixture A) link in adjacent sections.
    assert any(
        "adjacent" in f for f in blocking(sop.check("draft", text, {**CTX, "content_type": "outbound"}))
    )
    assert not any("adjacent" in f for f in blocking(sop.check("draft", text, CTX)))
    ctx = {
        **CTX,
        "content_type": "outbound",
        "anchors": [{"text": "SDS software", "url": "https://sdsmanager.com/us/sds-software/"}],
    }
    found = blocking(sop.check("draft", GOOD_DRAFT, ctx))
    assert any("appears 0 time(s)" in f for f in found)


def test_verdict_parsing():
    verdict, findings, suggestions = sop.parse_verdict(
        "VERDICT: REVISE\n\n## Findings\n1. Intro · no scope sentence · add it\n2. FAQ · bare Yes · mirror"
        "\n\n## Suggestions\n1. Add a worked example"
    )
    assert verdict == "REVISE" and len(findings) == 2 and findings[0].startswith("Intro")
    assert suggestions == ["Add a worked example"]
    assert sop.parse_verdict("**Verdict:** PASS\n\n## Findings\nNone.") == ("PASS", [], [])
    assert sop.parse_verdict("")[0] == "PASS"
    # A REVISE that lists only suggestions is a PASS: suggestions never block.
    assert (
        sop.parse_verdict("VERDICT: REVISE\n\n## Findings\nNone.\n\n## Suggestions\n1. Shorter intro")[0]
        == "PASS"
    )


def test_items_count_table_rows_too():
    rows = "\n".join(f"| Question {i}? | body |" for i in range(9))
    table = "| Question | Where |\n|---|---|\n" + rows
    assert len(sop._items(table)) == 9
    assert len(sop._items("- one\n- two\n" + table)) == 9  # the larger of the two formats counts


def test_rubrics_exist_for_every_sop_step():
    for key in sop.STEPS:
        assert sop.rubric(key), key


# ---- The loop ----


@pytest.fixture
def brief(admin_user):
    return ContentBrief.objects.create(
        topic="How long to keep SDSs",
        pkeyword="SDS retention requirements",
        skeywords=["how long to keep safety data sheets"],
        fkgl=9,
        region="US",
        content_type="seo_blog",
        created_by=admin_user,
    )


class SopLLM:
    """Answers the research step, then the reviewer (REVISE once, then PASS) and the revision."""

    def __init__(self, verdicts=("REVISE", "PASS"), revision=None, fail_reviewer=False):
        self.calls, self.verdicts, self.revision, self.fail_reviewer = (
            [],
            list(verdicts),
            revision,
            fail_reviewer,
        )

    def __call__(self, provider, model, messages, options):
        system, user = messages[0]["content"], messages[-1]["content"]
        self.calls.append((provider, model, user))
        if "SOP reviewer" in system:
            if self.fail_reviewer:
                raise ProviderError("rate_limited", "slow down", 429)
            verdict = self.verdicts.pop(0) if self.verdicts else "PASS"
            text = f"VERDICT: {verdict}\n\n## Findings\n" + (
                "1. Claims · claim 3 has no status · add it" if verdict == "REVISE" else "None."
            )
        elif "Findings to apply" in user:
            text = self.revision if self.revision is not None else GOOD_RESEARCH + "\nRevised once.\n"
        else:
            text = getattr(self, "generation", GOOD_RESEARCH)
        return GenerationResult(provider=provider, model=model, text=text, output_tokens=50, total_time=0.1)


def _autopilot_run(brief):
    return services.create_run(brief, forms.autopilot_config(brief.content_type), autopilot=True)


def test_autopilot_run_self_reviews_and_continues(brief, monkeypatch):
    fake = SopLLM()
    monkeypatch.setattr(executors, "generate", fake)
    run = _autopilot_run(brief)
    assert (
        run.autopilot and run.steps.get(key="research").self_review and not run.steps.get(key="research").gate
    )
    assert not run.steps.get(key="publish").self_review
    research = run.steps.get(key="research")
    execute_step(research.pk)
    research.refresh_from_db()
    assert research.status == StepRun.Status.APPROVED  # passed the SOP, so it continued
    version = research.latest_version
    log = version.metrics["sop"]
    assert log["passed"] and [r["verdict"] for r in log["rounds"]] == ["REVISE", "PASS"]
    assert log["rounds"][0]["revision"] == "applied" and "Revised once." in version.content
    assert "SOP self-review" in version.note and "Passed" in version.note
    assert run.steps.get(key="outline").status == StepRun.Status.QUEUED
    # generation, review, revision, review
    assert len(fake.calls) == 4


def test_step_holds_when_the_sop_is_not_met(brief, monkeypatch):
    monkeypatch.setattr(
        executors, "generate", SopLLM(verdicts=("REVISE",) * (settings.STUDIO_SOP_MAX_ROUNDS + 1))
    )
    run = _autopilot_run(brief)
    research = run.steps.get(key="research")
    execute_step(research.pk)
    research.refresh_from_db()
    assert research.status == StepRun.Status.READY
    log = research.latest_version.metrics["sop"]
    assert not log["passed"] and len(log["rounds"]) == settings.STUDIO_SOP_MAX_ROUNDS + 1
    assert "Held for your review" in research.latest_version.note
    run.refresh_from_db()
    assert run.status == "needs_review"


def test_blocking_checks_hold_even_when_the_reviewer_passes(brief, monkeypatch):
    bad = GOOD_RESEARCH.replace("## Claims", "## Evidence")
    monkeypatch.setattr(executors, "generate", SopLLM(verdicts=("PASS", "PASS", "PASS"), revision=bad))
    run = _autopilot_run(brief)
    research = run.steps.get(key="research")
    # The generation is good, the reviewer says PASS and no check blocks: it passes in one round.
    execute_step(research.pk)
    research.refresh_from_db()
    assert research.status == StepRun.Status.APPROVED
    assert len(research.latest_version.metrics["sop"]["rounds"]) == 1


def test_bad_revision_is_not_used(brief, monkeypatch):
    monkeypatch.setattr(
        executors, "generate", SopLLM(verdicts=("REVISE", "PASS"), revision="## Short\n\nnothing")
    )
    run = _autopilot_run(brief)
    research = run.steps.get(key="research")
    execute_step(research.pk)
    research.refresh_from_db()
    log = research.latest_version.metrics["sop"]
    assert log["rounds"][0]["revision"].startswith("not used")
    assert research.latest_version.content.startswith("## Search Intent")
    # The next round reviews the unchanged text (and tells the model why); here it passes.
    assert len(log["rounds"]) == 2 and log["passed"]
    assert research.status == StepRun.Status.APPROVED


def test_house_mechanics_are_fixed_before_the_checks(brief, monkeypatch):
    dashed = GOOD_RESEARCH.replace("Informational;", "Informational —").replace("Explainer,", "“Explainer”,")
    fake = SopLLM(verdicts=("PASS",))
    fake.generation = dashed
    monkeypatch.setattr(executors, "generate", fake)
    run = _autopilot_run(brief)
    research = run.steps.get(key="research")
    execute_step(research.pk)
    research.refresh_from_db()
    log = research.latest_version.metrics["sop"]
    assert log["passed"] and log["rounds"][0]["fixes"].get("dashes") == 1
    assert log["rounds"][0]["fixes"].get("curly quotes") == 2
    assert not any("dash" in c or "curly" in c for c in log["rounds"][0]["checks"])
    assert "—" not in research.latest_version.content and "“" not in research.latest_version.content


def test_reviewer_failure_keeps_the_output_and_holds(brief, monkeypatch):
    monkeypatch.setattr(executors, "generate", SopLLM(fail_reviewer=True))
    run = _autopilot_run(brief)
    research = run.steps.get(key="research")
    execute_step(research.pk)
    research.refresh_from_db()
    assert research.status == StepRun.Status.READY
    log = research.latest_version.metrics["sop"]
    assert not log["passed"] and "free limit" in log["error"]
    assert research.latest_version.content.startswith("## Search Intent")


def test_gated_step_with_self_review_still_waits(brief, monkeypatch):
    monkeypatch.setattr(executors, "generate", SopLLM(verdicts=("PASS",)))
    run = services.create_run(brief, {"research": {"gate": True, "self_review": True}})
    research = run.steps.get(key="research")
    execute_step(research.pk)
    research.refresh_from_db()
    assert research.status == StepRun.Status.READY and research.latest_version.metrics["sop"]["passed"]


# ---- Wizard and screens ----


def test_wizard_autopilot_mode(admin_client):
    response = admin_client.post(
        reverse("studio:brief_new"),
        {
            "content_type": "seo_blog",
            "topic": "Autopilot topic",
            "pkeyword": "autopilot keyword",
            "fkgl": "9",
            "region": "US",
            "comprehension": "practitioner",
            "cta_style": "subtle",
            "mode": "autopilot",
            "action": "start",
        },
    )
    assert response.status_code == 302
    brief = ContentBrief.objects.get(topic="Autopilot topic")
    run = brief.runs.first()
    assert run.autopilot
    steps = {s.key: s for s in run.steps.all()}
    assert all(not s.gate for s in steps.values())
    assert (
        steps["draft"].self_review and steps["research"].self_review and not steps["hero_image"].self_review
    )
    html = admin_client.get(reverse("studio:run", args=[run.pk])).content.decode()
    assert "Autopilot" in html and "SOP self-review" in html


def test_wizard_shows_the_mode_switch_and_sop_column(admin_client):
    html = admin_client.get(reverse("studio:brief_new")).content.decode()
    assert 'name="mode" value="autopilot"' in html and "step_draft_self_review" in html
    assert "step_publish_self_review" not in html


def test_brief_list_can_start_an_autopilot_run(admin_client, brief):
    response = admin_client.post(reverse("studio:briefs"), {"brief": brief.pk, "mode": "autopilot"})
    assert response.status_code == 302
    run = brief.runs.first()
    assert run.autopilot and run.steps.get(key="draft").self_review and not run.steps.get(key="draft").gate


def test_guest_post_anchors_are_parsed_and_reach_the_prompt(admin_client):
    response = admin_client.post(
        reverse("studio:brief_new"),
        {
            "content_type": "outbound",
            "topic": "Chemical storage",
            "pkeyword": "chemical storage",
            "fkgl": "9",
            "region": "UK",
            "comprehension": "practitioner",
            "cta_style": "subtle",
            "site": "Safety Blog",
            "site_domain": "https://example.com",
            "source_reference": "Guest Post Plan, row 14",
            "anchors_text": "SDS software | https://sdsmanager.com/uk/sds-software/\nchemical inventory | https://sdsmanager.com/uk/inventory/",
            "action": "save",
        },
    )
    assert response.status_code == 302
    brief = ContentBrief.objects.get(topic="Chemical storage")
    assert brief.anchors == [
        {"text": "SDS software", "url": "https://sdsmanager.com/uk/sds-software/"},
        {"text": "chemical inventory", "url": "https://sdsmanager.com/uk/inventory/"},
    ]
    from apps.studio import prompting

    table = prompting.brief_table(brief)
    assert "sds-software" in table and "row 14" in table


def test_bad_anchor_lines_are_refused(admin_client):
    response = admin_client.post(
        reverse("studio:brief_new"),
        {
            "content_type": "outbound",
            "topic": "Chemical storage",
            "pkeyword": "chemical storage",
            "fkgl": "9",
            "region": "UK",
            "comprehension": "practitioner",
            "cta_style": "subtle",
            "site_domain": "https://example.com",
            "anchors_text": "no url here",
            "action": "save",
        },
    )
    assert response.status_code == 200 and "anchor text | https" in response.content.decode()


def test_prompts_adapt_to_the_content_type(brief):
    from apps.studio import prompting

    run = services.create_run(brief, {})
    draft = prompting.render("draft", prompting.context_for(run.steps.get(key="draft")))
    assert "an sdsmanager.com article" in draft[0]["content"]
    assert "at least three sdsmanager.com links" in draft[1]["content"]
    brief.content_type = "outbound"
    brief.site_domain = "https://example.com"
    brief.save()
    run = services.create_run(brief, {})
    draft = prompting.render("draft", prompting.context_for(run.steps.get(key="draft")))
    assert "a guest post for a third-party website" in draft[0]["content"]
    assert "No product link, no anchor and no promotion in the close" in draft[1]["content"]
    assert "at least three sdsmanager.com links" not in draft[1]["content"]


def test_outline_files_can_be_downloaded(admin_client, brief):
    run = services.create_run(brief, {})
    outline = run.steps.get(key="outline")
    services.add_version(outline, GOOD_OUTLINE)
    bare = admin_client.get(reverse("studio:run_export", args=[run.pk, "outline"]))
    assert bare.status_code == 200 and bare["Content-Disposition"].endswith(
        'outline-sds-retention-requirements.md"'
    )
    text = bare.content.decode()
    assert text.startswith("# SDS Retention Requirements") and "\n## Key Takeaways\n" in text
    assert "### Can Safety Data Sheets Be Stored Electronically?" in text and "H2:" not in text
    detailed = admin_client.get(reverse("studio:run_export", args=[run.pk, "outline_detailed"]))
    assert detailed.status_code == 200 and "## Structure Decisions" in detailed.content.decode()
    html = admin_client.get(reverse("studio:run", args=[run.pk]) + "?step=outline").content.decode()
    assert "Download the headings-only outline" in html


def test_section_names_and_heading_lines_are_matched_loosely():
    loose = GOOD_OUTLINE.replace("## Headings-Only Outline", "## Headings only outline:").replace(
        "\nH2: Key Takeaways", "\n- H2: Key Takeaways"
    )
    assert blocking(sop.check("outline", loose, CTX)) == []
    research = GOOD_RESEARCH.replace("## Questions for the Requester", "## Questions For The Requester")
    assert blocking(sop.check("research", research, CTX)) == []


def test_an_intro_line_in_the_headings_only_outline_is_ignored():
    with_intro = GOOD_OUTLINE.replace("H1: SDS Retention", "H1: SDS Retention").replace(
        "\nH2: Key Takeaways\n", "\nH2: Intro\nH2: Key Takeaways\n"
    )
    assert blocking(sop.check("outline", with_intro, CTX)) == []


def test_a_plan_revision_that_drops_a_section_is_refused():
    ok, reason = sop._guard(
        "outline", GOOD_OUTLINE, GOOD_OUTLINE.replace("## Headings-Only Outline", "### Headings")
    )
    assert not ok and "Headings-Only Outline" in reason
    ok, _ = sop._guard("outline", GOOD_OUTLINE, GOOD_OUTLINE + "\n## Extra Notes\n\nmore\n")
    assert ok


def test_fixed_component_headings_are_normalised():
    plan = GOOD_OUTLINE.replace(
        "H2: Key Takeaways", "H2: What Are the Key Takeaways for SDS Retention?"
    ).replace("H2: Frequently Asked Questions", "**H2:** SDS Retention Frequently Asked Questions")
    fixed, n = sop.normalise_fixed_headings(plan)
    assert n == 2 and "\nH2: Key Takeaways\n" in fixed and "\nH2: Frequently Asked Questions\n" in fixed
    article, n = sop.normalise_fixed_headings(
        GOOD_DRAFT.replace("## Key Takeaways", "## Key Takeaways on SDS Retention")
    )
    assert n == 1 and "\n## Key Takeaways\n" in article
    assert sop.normalise_fixed_headings(GOOD_DRAFT)[1] == 0


def test_two_refused_revisions_in_a_row_stop_the_loop(brief, monkeypatch):
    fake = SopLLM(verdicts=("REVISE",) * 6, revision="## Short\n\nnothing")
    monkeypatch.setattr(executors, "generate", fake)
    run = _autopilot_run(brief)
    research = run.steps.get(key="research")
    execute_step(research.pk)
    research.refresh_from_db()
    log = research.latest_version.metrics["sop"]
    assert len(log["rounds"]) == 2 and "stopped after two refused" in log["rounds"][1]["revision"]
    assert research.status == StepRun.Status.READY


def test_draft_guard_keeps_links_and_negations_but_allows_rewording():
    reworded = GOOD_DRAFT.replace(
        "You keep a record for 30 years", "Employers keep the record for three decades"
    )
    assert sop._guard("draft", GOOD_DRAFT, reworded)[0]
    no_link = GOOD_DRAFT.replace("(https://sdsmanager.com/us/ehs-software/)", "(https://example.com/)")
    ok, reason = sop._guard("draft", GOOD_DRAFT, no_link)
    assert not ok and "dropped the link" in reason
    flipped = GOOD_DRAFT.replace("Safety data sheets don't expire", "Safety data sheets expire")
    assert not sop._guard("draft", GOOD_DRAFT, flipped)[0]


def test_a_draft_heading_may_be_reworded_in_place_but_not_dropped():
    # Run 20: the check asked for the keyword in an H2 and every revision doing it was refused as a rename.
    renamed = GOOD_DRAFT.replace(
        "## What Counts as an Exposure Record?", "## What Counts as an SDS Exposure Record?"
    )
    assert sop._guard("draft", GOOD_DRAFT, renamed)[0]
    dropped = GOOD_DRAFT.replace("## What Counts as an Exposure Record?\n", "")
    assert not sop._guard("draft", GOOD_DRAFT, dropped)[0]
    plan = "## Search Intent\n\nInformational, how-to.\n\n## H1 Options\n\n1. One\n"
    assert not sop._guard("outline", plan, plan.replace("## Search Intent", "## Intent"))[0]


def test_broken_bold_links_are_repaired():
    from apps.quality import house

    fixed, counts = house.mechanical_fix("See **[our guide]**(https://sdsmanager.com/us/x/) now.\n")
    assert counts["broken bold links"] == 1 and "[**our guide**](https://sdsmanager.com/us/x/)" in fixed


def test_invented_internal_urls_are_blocked():
    ctx = {**CTX, "allowed_urls": {"https://sdsmanager.com/us/ehs-software/"}}
    found = blocking(sop.check("draft", GOOD_DRAFT, ctx))
    assert any("sds-guide" in f and "invented" in f for f in found)
    assert not any("ehs-software" in f for f in found)
    ok_ctx = {
        **CTX,
        "allowed_urls": {
            "https://sdsmanager.com/us/ehs-software/",
            "https://sdsmanager.com/us/sds-management-articles/sds-guide/",
        },
    }
    assert not any("invented" in f for f in blocking(sop.check("draft", GOOD_DRAFT, ok_ctx)))
    editor = GOOD_DRAFT.replace(
        "(https://sdsmanager.com/us/sds-management-articles/sds-guide/)", "(wagtail://page?id=12)"
    )
    assert not any("invented" in f for f in blocking(sop.check("draft", editor, ctx)))


def test_allowed_urls_come_from_the_inputs(brief):
    run = services.create_run(brief, {})
    research = run.steps.get(key="research")
    services.add_version(
        research, "## Sources\n- https://www.osha.gov/laws-regs and https://sdsmanager.com/us/x/\n"
    )
    research.status = StepRun.Status.APPROVED
    research.save()
    allowed = sop.allowed_urls(run.steps.get(key="draft"))
    assert "https://sdsmanager.com/us/x/" in allowed and "https://www.osha.gov/laws-regs" in allowed
    assert any("ehs-software" in url for url in allowed)  # the product registry


def test_an_edit_revision_may_drop_an_invented_url():
    invented = GOOD_DRAFT.replace(
        "(https://sdsmanager.com/us/sds-management-articles/sds-guide/) lists the record categories",
        "(https://sdsmanager.com/library) lists the record categories",
    )
    cleaned = invented.replace(
        "[SDS management\nguide](https://sdsmanager.com/library) lists the record categories OSHA names.", ""
    )
    assert not sop._guard("review_edit", invented, cleaned)[0]
    assert sop._guard("review_edit", invented, cleaned, droppable=["https://sdsmanager.com/library"])[0]
    assert (
        sop.INVENTED_URL.match(
            "[block] the link https://sdsmanager.com/library isn't in the inputs (x)"
        ).group(1)
        == "https://sdsmanager.com/library"
    )


def test_hero_holds_in_autopilot_when_a_person_must_look():
    assert executors.hero_needs_a_look(["Readable text or logo in the photo: garbled label"], True)
    assert executors.hero_needs_a_look(["Safety: no gloves"], True)
    assert executors.hero_needs_a_look([], False)
    assert not executors.hero_needs_a_look(["The left 7% of the frame is a mirrored fill"], True)


def test_metadata_options_and_hyphens_pass_the_house_mechanics():
    from apps.quality import house

    fixed, counts = house.mechanical_fix("A 5‑Minute Guide – For Supervisors\n")
    assert fixed.strip() == "A 5-Minute Guide: For Supervisors" and counts["typographic hyphens"] == 1


def test_dashes_in_headings_and_titles_become_colons():
    from apps.quality import house

    fixed, _ = house.mechanical_fix("## Take Action — Digitize Your SDS Management\n\nA – B body.\n")
    assert fixed.startswith("## Take Action: Digitize Your SDS Management\n") and "A, B body." in fixed
    assert (
        house.mechanical_fix("How to Read an SDS – 5-Minute Guide")[0].strip()
        == "How to Read an SDS: 5-Minute Guide"
    )


def test_rubrics_carry_the_vendored_reference_rules_and_the_guest_post_variant():
    draft = sop.rubric("draft")
    for rule in (
        "### Flow and reasoning",
        "### Voice",
        "### AI patterns",
        "### Formatting",
        "### Links",
        "plot-free",
        "one home",
    ):
        assert rule in draft, rule
    assert "SITE_PROFILE" not in draft
    outbound = sop.rubric("draft", "outbound")
    assert outbound.startswith(draft) and "SITE_PROFILE governs the surface" in outbound
    assert sop.rubric("draft", "seo_blog") == draft
    assert "NARRATIVE_MODE held" in sop.rubric("review_edit", "outbound")
    assert "distinct piece" in sop.rubric("localise")


def test_blog_shaped_components_are_advisory_on_a_guest_post():
    text = GOOD_DRAFT.replace("## Key Takeaways\n", "## Why It Matters\n").replace(
        "## Frequently Asked Questions", "## Common Questions"
    )
    assert any("Key Takeaways" in f for f in blocking(sop.check("draft", text, CTX)))
    guest = {**CTX, "content_type": "outbound"}
    assert not any(
        "Key Takeaways" in f or "Frequently Asked" in f for f in blocking(sop.check("draft", text, guest))
    )


def test_bold_labels_in_a_plan_become_headings():
    bolded = (
        GOOD_OUTLINE.replace("## Search Intent", "**Search Intent**")
        .replace("## Headings-Only Outline", "**Headings-Only Outline**  ")
        .replace("H2: Key Takeaways", "**H2: Key Takeaways**")
    )
    assert any("missing section" in f for f in blocking(sop.check("outline", bolded, CTX)))
    fixed, n = sop.normalise_plan_headings(bolded)
    assert n == 2 and fixed.startswith("## Search Intent\n") and "\n## Headings-Only Outline\n" in fixed
    assert "**H2: Key Takeaways**" in fixed  # plan marker lines are the headings-only parser's job
    assert blocking(sop.check("outline", fixed, CTX)) == []


def test_meta_narration_catches_this_section_outlines():
    text = GOOD_DRAFT.replace(
        "You keep a record for 30 years", "This section outlines the rule. You keep a record for 30 years"
    )
    assert any("meta narration" in f for f in blocking(sop.check("draft", text, CTX)))
    assert not any("meta narration" in f for f in blocking(sop.check("draft", GOOD_DRAFT, CTX)))


def test_metadata_shortfall_is_a_log_note_not_a_reviewer_check():
    ctx = {**CTX, "metadata_counts": {"title": 3, "meta": 3, "slug": 3, "tags": 1, "excerpt": 1}}
    notes = [f for f in sop.check("draft", GOOD_DRAFT, ctx) if f.severity == "note"]
    assert len(notes) == 1 and "tags, excerpt" in notes[0].text
    assert blocking(sop.check("draft", GOOD_DRAFT, ctx)) == []


def test_link_carrier_sentences_are_blocked():
    pointer = GOOD_DRAFT.replace(
        "Keep the version in use at the time of exposure.",
        "Keep the version in use at the time of exposure. For a deeper look at creating job-specific safety "
        "documents, refer to the job safety analysis guide.",
    )
    found = blocking(sop.check("draft", pointer, CTX))
    assert any("exists only to point at another page" in f for f in found)
    assert not any("point at another page" in f for f in blocking(sop.check("draft", GOOD_DRAFT, CTX)))
    see = GOOD_DRAFT.replace(
        "Keep the version in use at the time of exposure.",
        "To manage changes, see the management-of-change resource.",
    )
    assert any("point at another page" in f for f in blocking(sop.check("draft", see, CTX)))


def test_the_reviser_is_told_the_length_floor():
    words = len(GOOD_DRAFT.split())
    rule = sop.length_rule("draft", GOOD_DRAFT, {**CTX, "wordcount": words + 500})
    assert f"Keep at least {int(words * 0.9)}" in rule
    assert "never shorten it" in rule
    assert "never shorten it" not in sop.length_rule("draft", GOOD_DRAFT, {**CTX, "wordcount": 10})
    assert "guide" not in sop.length_rule("outline", GOOD_DRAFT, {**CTX, "wordcount": 5000})
    messages = sop.prompting.render("sop_revise", {"length_rule": rule, "findings": "1. x"})
    assert "Keep at least" in messages[1]["content"]


def test_headings_carry_the_keyword_as_a_natural_variant():
    pk = "how to read a safety data sheet"
    assert sop.carries_keyword("How to Read an SDS Quickly in the Field", pk)
    assert sop.carries_keyword("How to Read Safety Data Sheets", pk)
    assert sop.carries_keyword("How To Read A Safety Data Sheet: Core Steps", pk)
    assert not sop.carries_keyword("The 16 SDS Sections Explained", pk)
    assert sop.carries_keyword("Which SDS Retention Requirements Apply?", "SDS retention requirements")
    assert sop.first_h2_answers("How to Read an SDS in Five Steps", pk)
    assert not sop.first_h2_answers("What Is an SDS and Why It Matters", pk)
    assert sop.first_h2_answers("What Are the SDS Retention Rules?", "SDS retention requirements")
    variant = GOOD_DRAFT.replace("Under OSHA?", "Under OSHA? (Retention Rules)")
    assert not any("carries the primary keyword" in f for f in blocking(sop.check("draft", variant, CTX)))


def test_the_first_body_h2_should_answer_the_query():
    ctx = {**CTX, "pkeyword": "how to read a safety data sheet"}
    text = GOOD_DRAFT.replace(
        "## What Are the SDS Retention Requirements Under OSHA?", "## What Is an SDS and Why It Matters"
    )
    found = [str(f) for f in sop.check("draft", text, ctx)]
    assert any("doesn't answer the primary query" in f and f.startswith("[advise]") for f in found)


def test_keyword_tacked_onto_headings_is_blocked_but_natural_use_is_not():
    # Run 20's revision appended the keyword to every H2.
    stuffed = GOOD_DRAFT
    for heading in (
        "What Counts as an Exposure Record?",
        "Do Safety Data Sheets Expire?",
        "Keep Every SDS Where Your Auditor Can Find It",
    ):
        stuffed = stuffed.replace(f"## {heading}", f"## {heading.rstrip('?')} for SDS Retention Requirements")
    assert any("tacked onto the end of 3 headings" in f for f in blocking(sop.check("draft", stuffed, CTX)))
    assert not any("tacked onto" in f for f in blocking(sop.check("draft", GOOD_DRAFT, CTX)))
    # The keyword opening many headings is natural (the approved JSA article does it 17 times).
    natural = GOOD_DRAFT.replace(
        "## What Counts as an Exposure Record?", "## SDS Retention Requirements for Labs"
    )
    natural = natural.replace("## Do Safety Data Sheets Expire?", "## SDS Retention Requirements and Expiry")
    assert not any("tacked onto" in f for f in blocking(sop.check("draft", natural, CTX)))


def test_reference_style_url_links_are_repaired():
    fixed, counts = sop.house.mechanical_fix("See the [JSA guide][https://sdsmanager.com/us/jsa/] first.\n")
    assert "[JSA guide](https://sdsmanager.com/us/jsa/)" in fixed and counts["broken links"] == 1


def test_relative_and_marker_link_targets_are_blocked_and_verify_links_unwrapped():
    ctx = {**CTX, "allowed_urls": set()}
    found = blocking(sop.check_sourced_urls("Use the [training page](/resources/training) first.", ctx))
    assert any("'/resources/training'" in f for f in found)
    fixed, counts = sop.house.mechanical_fix("Pair it with a [job safety analysis]([VERIFY]) review.\n")
    assert "a job safety analysis [VERIFY] review." in fixed and counts["links to [VERIFY]"] == 1
    assert not blocking(sop.check_sourced_urls("Read [Section 8](#section-8).", ctx))


def test_the_reviser_sees_the_allowed_links_on_article_steps_only():
    base = {"related_articles": "- [JSA](https://sdsmanager.com/us/jsa/)", "product_pages": "- EHS"}
    assert "https://sdsmanager.com/us/jsa/" in sop.link_sources("draft", base)
    assert "never write a URL from memory" in sop.link_sources("review_edit", base)
    assert sop.link_sources("outline", base) == ""


def test_spaced_markers_are_normalised_and_still_hold_publishing():
    # Run 20 wrote "[ SRC: url ]", which the strict marker pattern let through to publishing.
    text = "## Rules\n\nA fact [ SRC: https://www.osha.gov/x ] and a claim [ verify ]. Keep [VERIFY: date].\n"
    kinds = [m["kind"] for m in sop.house.find_markers(text)]
    assert kinds.count("SRC") == 1 and kinds.count("VERIFY") == 2
    fixed, counts = sop.house.mechanical_fix(text)
    assert "[SRC: https://www.osha.gov/x]" in fixed and "a claim [VERIFY]." in fixed
    assert "[VERIFY: date]" in fixed and counts["markers normalised"] == 2
    assert sop.house.strip_sources("A fact [ SRC: https://www.osha.gov/x ].") == "A fact."


def test_a_blog_close_must_link_a_product_page():
    close = "## Keep Every SDS Where Your Auditor Can Find It"
    body = GOOD_DRAFT.split(close, 1)[1].split("\n## ", 1)[0]
    unlinked = GOOD_DRAFT.replace(body, "\n\nPaper binders go missing.\n\n**Start Free Trial**\n")
    assert any("links no product page" in f for f in blocking(sop.check("draft", unlinked, CTX)))
    article = GOOD_DRAFT.replace(
        body,
        "\n\nKeep a [retention log](https://sdsmanager.com/us/sds-management-articles/sds-retention/).\n",
    )
    assert any("links an article" in f for f in blocking(sop.check("draft", article, CTX)))
    assert not any("product page" in f for f in blocking(sop.check("draft", GOOD_DRAFT, CTX)))


def test_regulation_subsections_must_come_from_the_inputs_or_carry_verify():
    ctx = {**CTX, "allowed_citations": {"1910.1200(g)(8)", "1910.1200(h)"}}
    text = (
        "## Rules\n\nEmployers keep sheets accessible under 1910.1200(g)(8). Training is required by "
        "29 CFR 1910.1200 (c)(1). The format follows 1910.1200(g). "
        "Updates follow § 1910.1200(g)(5) [VERIFY].\n"
    )
    found = blocking(sop.check_citations(text, ctx))
    assert len(found) == 1 and "1910.1200 (c)(1)" in found[0]
    assert sop.check_citations(text, CTX) == []  # no inputs known: nothing to compare against
    as_logged = str(sop.check_citations(text, ctx)[0])  # what the loop reads back
    assert sop.INVENTED_CITATION.match(as_logged).group(1) == "1910.1200 (c)(1)"


def test_a_comma_between_topic_and_qualifier_in_a_heading_is_blocked():
    text = GOOD_DRAFT.replace("## Do Safety Data Sheets Expire?", "## Worked Example, Acetone SDS")
    assert any("Worked Example, Acetone SDS" in f for f in blocking(sop.check("draft", text, CTX)))
    listed = GOOD_DRAFT.replace("## Do Safety Data Sheets Expire?", "## Gloves, Goggles and Respirators")
    assert not any("with a comma" in f for f in blocking(sop.check("draft", listed, CTX)))
    assert not any("with a comma" in f for f in blocking(sop.check("draft", GOOD_DRAFT, CTX)))
    for fine in (
        "If an SDS Is Missing, What Should You Do?",
        "Managing 1,000 Chemicals Without Spreadsheets",
        "What Is an SDS: A Short, Practical Guide",
    ):
        text = GOOD_DRAFT.replace("## Do Safety Data Sheets Expire?", f"## {fine}")
        assert not any("with a comma" in f for f in blocking(sop.check("draft", text, CTX))), fine


def test_the_skills_link_and_flow_scripts_run_as_checks():
    text = GOOD_DRAFT.replace(
        "Keep the version in use at the time of exposure.",
        "Keep it in [SDS software](https://sdsmanager.com/us/) and [EHS](https://sdsmanager.com/us/ehs-software/).",
    )
    found = [str(f) for f in sop.check_skill_scripts(text)]
    assert any(f.startswith("[block] two links in one sentence (link_check)") for f in found)
    assert any("sdsmanager.com links; one per section" in f for f in found)
    opener = GOOD_DRAFT.replace(
        "## Do Safety Data Sheets Expire?\n",
        "## Do Safety Data Sheets Expire?\n\n### Shelf Life\n\nThis covers it.\n",
    )
    assert any(
        f.endswith("(editorial_flow_check)") and f.startswith("[advise]")
        for f in map(str, sop.check_skill_scripts(opener))
    )
    assert not [f for f in sop.check_skill_scripts(GOOD_DRAFT) if f.severity == "block"]


def test_verify_marker_forms_are_all_held_and_kept_inside_their_sentence():
    for marker in ("[VERIFY at publication]", "[VERIFY-AUTHOR: date of the audit]", "[verify]"):
        assert [m["kind"] for m in sop.house.find_markers(f"## A\n\nA claim {marker}.\n")] == ["VERIFY"]
    fixed, counts = sop.house.mechanical_fix("Training follows 1910.1200(h)(3). [VERIFY] Next point.\n")
    assert fixed == "Training follows 1910.1200(h)(3) [VERIFY]. Next point.\n"
    ctx = {**CTX, "allowed_citations": set()}
    assert sop.check_citations(fixed, ctx) == []  # the fix the finding asks for now satisfies it


def test_a_pointer_sentence_may_take_its_link_with_it():
    url = "https://sdsmanager.com/us/sds-management-articles/job-safety-analysis/"
    pointer = f"For more details, see our article on [job safety analysis]({url})."
    text = GOOD_DRAFT.replace(
        "Keep the version in use at the time of exposure.",
        "Keep the version in use at the time of exposure. " + pointer,
    )
    match = sop.LINK_CARRIER.search(text)
    assert match and url in match.group(0)  # the sentence runs past the dots inside the URL
    assert not sop._guard("draft", text, text.replace(" " + pointer, ""))[0]
    assert sop._guard("draft", text, text.replace(" " + pointer, ""), droppable=[url])[0]


# ---- Phase 2 (docs/sop-audit.md): findings carry a level and permissions; the loop re-checks ----


class ScriptedCall:
    """A `call` for run_loop: reviewer replies and revisions in order, recording what was sent."""

    def __init__(self, verdicts, revisions):
        self.verdicts, self.revisions, self.sent = list(verdicts), list(revisions), []

    def __call__(self, prompt_name, context, task):
        self.sent.append((prompt_name, context))
        if prompt_name == "sop_review":
            verdict = self.verdicts.pop(0) if self.verdicts else "PASS"
            # "REVISE3" returns three findings.
            count = int(verdict[6:] or 1) if verdict.startswith("REVISE") else 0
            findings = "\n".join(f"{i}. Section {i} · a rubric line · a fix" for i in range(1, count + 1))
            verdict = "REVISE" if count else verdict
            return f"VERDICT: {verdict}\n\n## Findings\n{findings or 'None.'}", "fake/reviewer"
        return self.revisions.pop(0), "fake/writer"


@pytest.fixture
def draft_step(brief, monkeypatch):
    monkeypatch.setattr(sop, "context_from", lambda step: dict(CTX))
    return services.create_run(brief, {}).steps.get(key="draft")


NO_FAQ = (
    "### Do You Need to Keep an SDS for a Discontinued Product?\n\n"
    "An SDS for a discontinued product stays in the archive for 30 years after the last use."
)


def test_the_fix_a_finding_asks_for_is_allowed_bare_no_faq(draft_step):
    bare = GOOD_DRAFT.replace(
        NO_FAQ,
        "### Can an SDS Be Thrown Away When a Product Is Discontinued?\n\n"
        "No, it stays in the archive for 30 years after the last use.",
    )
    # Mirroring the subject drops the "No".
    fixed = bare.replace("No, it stays", "An SDS for a discontinued product stays")
    assert any("bare Yes/No" in f for f in blocking(sop.check("draft", bare, CTX)))
    assert not any("bare Yes/No" in f for f in blocking(sop.check("draft", fixed, CTX)))
    call = ScriptedCall(["REVISE", "PASS"], [fixed])
    result = sop.run_loop(draft_step, bare, call, max_rounds=2)
    assert result.passed, result.rounds[0].revision
    assert result.rounds[0].revision == "applied" and "No, an SDS" not in result.text
    # Without the finding's permission the same edit is a lost negation.
    assert not sop._guard("draft", bare, fixed)[0]


def test_a_yes_or_no_that_mirrors_the_question_is_fine():
    # The approved WHS article (Fixture A): "Yes," followed by the question's own subject.
    mirrored = GOOD_DRAFT.replace(
        NO_FAQ,
        "### Does WHS Risk Management Apply to Volunteers?\n\n"
        "Yes, WHS risk management applies to volunteers the same way it applies to paid workers.",
    )
    assert not any("bare Yes/No" in f for f in blocking(sop.check("draft", mirrored, CTX)))
    bare = mirrored.replace("Yes, WHS risk management applies to volunteers", "Yes, a PCBU owes the duty")
    assert any("bare Yes/No" in f for f in blocking(sop.check("draft", bare, CTX)))


def test_a_revision_that_introduces_new_blocks_is_refused(draft_step):
    comma = GOOD_DRAFT.replace("## Do Safety Data Sheets Expire?", "## Worked Example, SDS Expiry")
    worse = comma.replace("## Worked Example, SDS Expiry", "## Worked Example: SDS Expiry").replace(
        "Keep the version in use at the time of exposure.",
        "Keep the version in use at the time of exposure. In this section, we look at expiry.",
    )
    call = ScriptedCall(["REVISE", "REVISE"], [worse, worse])
    result = sop.run_loop(draft_step, comma, call, max_rounds=2)
    assert "introduced new problems: meta narration" in result.rounds[0].revision
    assert not result.passed and "In this section" not in result.text


def test_structural_blocks_go_back_to_the_step_not_to_the_reviser(draft_step):
    no_takeaways = re.sub(r"## Key Takeaways\n\n(?:- .*\n)+\n", "", GOOD_DRAFT)
    assert "Key Takeaways" not in no_takeaways
    call = ScriptedCall(["PASS"], [])
    result = sop.run_loop(draft_step, no_takeaways, call, max_rounds=2)
    assert not result.passed and result.route == "send_back"
    assert any("Key Takeaways" in f for f in result.routed)
    assert [name for name, _ in call.sent] == ["sop_review"]  # nothing went to a line reviser


def test_send_back_regenerates_the_draft_once_and_keeps_the_better_result(draft_step, monkeypatch):
    no_takeaways = re.sub(r"## Key Takeaways\n\n(?:- .*\n)+\n", "", GOOD_DRAFT)
    notes = []

    def regenerate(step):
        notes.append(step.regenerate_note)
        return executors.StepOutput(content=GOOD_DRAFT, provider="fake", model="writer")

    monkeypatch.setattr(executors, "EXECUTORS", {**executors.EXECUTORS, "draft": regenerate})
    monkeypatch.setattr(sop, "run_loop", _loop_with(ScriptedCall(["PASS"] * 4, [])))
    output = sop.apply(
        draft_step, executors.StepOutput(content=no_takeaways, provider="fake", model="writer")
    )
    log = output.extra_metrics["sop"]
    assert log["sent_back"] and log["passed"] and "## Key Takeaways" in output.content
    assert "Key Takeaways" in notes[0] and draft_step.regenerate_note == ""


def _loop_with(call):
    real = sop.run_loop

    def run(step, text, _call, max_rounds=None):
        return real(step, text, call, max_rounds=2)

    return run


def test_the_best_round_is_kept_on_a_hold(draft_step):
    comma = GOOD_DRAFT.replace("## Do Safety Data Sheets Expire?", "## Worked Example, SDS Expiry")
    reworded = comma.replace("Keep the version in use", "Keep the sheet version in use")
    # Round 1: one block, one reviewer finding. The revision keeps the block and round 2 has three findings.
    call = ScriptedCall(["REVISE1", "REVISE3"], [reworded])
    result = sop.run_loop(draft_step, comma, call, max_rounds=1)
    assert not result.passed and result.best_round == 1
    assert "Keep the version in use" in result.text  # round 1's text, not the worse revision
    # When the later round is no worse, the later text stands.
    call = ScriptedCall(["REVISE1", "REVISE1"], [reworded])
    result = sop.run_loop(draft_step, comma, call, max_rounds=1)
    assert result.best_round is None and "Keep the sheet version in use" in result.text


def test_near_miss_plan_section_names_are_matched_and_sub_labels_stay_bold():
    plan = (
        "## Search Intent\n\nHow-to.\n\n## Keyword & Anchor Map\n\n| a | b | c |\n\n"
        "## Cannibalisation\n\nNo overlap.\n\n## Claims\n\n**Regulatory claims**\n\n- one\n"
    )
    text, count = sop.canonical_section_names(plan, sop.RESEARCH_SECTIONS + sop.OUTLINE_SECTIONS)
    assert "## Keyword and Anchor Map" in text and "## Cannibalization" in text and count == 2
    promoted, n = sop.normalise_plan_headings(plan, sop.RESEARCH_SECTIONS)
    assert "**Regulatory claims**" in promoted and n == 0
    assert sop.normalise_plan_headings("**Search Intent**\n\nHow-to.\n", sop.RESEARCH_SECTIONS)[1] == 1


def test_findings_carry_the_permissions_their_fix_needs():
    url = "https://sdsmanager.com/us/made-up/"
    text = GOOD_DRAFT.replace("(https://sdsmanager.com/us/ehs-software/)", f"({url})")
    found = sop.check("draft", text, {**CTX, "allowed_urls": {"https://sdsmanager.com/us/ehs-software/"}})
    invented = next(f for f in found if "isn't in the inputs" in f.text and url in f.text)
    assert invented.allows["drop_urls"] == [url] and invented.level == "line"
    merged = sop.permissions(found)
    assert url in merged["drop_urls"]
    takeaways = sop.check("draft", re.sub(r"## Key Takeaways\n\n(?:- .*\n)+\n", "", GOOD_DRAFT), CTX)
    assert any(f.level == "structural" for f in takeaways)


def test_the_reverse_outline_compares_the_article_with_the_approved_plan():
    plan = sop.outline_plan(GOOD_OUTLINE)
    assert plan["planned_h2s"] and "Key Takeaways" not in plan["planned_h2s"]
    # GOOD_OUTLINE and GOOD_DRAFT were written separately (the check rightly reports the outline's
    # "How Long Do You Keep Safety Data Sheets?" as missing), so plan from the draft's own sections here.
    assert sop.check_reverse_outline(GOOD_DRAFT, {**CTX, **plan})
    own = [
        n
        for n, _ in sop._sections(GOOD_DRAFT)[1:]
        if n not in ("Key Takeaways", "Frequently Asked Questions")
    ]
    ctx = {**CTX, "planned_h2s": [n for n in own if n != "References"]}
    assert sop.check_reverse_outline(GOOD_DRAFT, ctx) == []
    first = ctx["planned_h2s"][0]
    dropped = re.sub(rf"## {re.escape(first)}\n\n(?:.*\n)+?(?=## )", "", GOOD_DRAFT)
    found = [str(f) for f in sop.check_reverse_outline(dropped, ctx)]
    assert any("missing from the article" in f and first in f for f in found)
    assert all(f.startswith("[advise]") for f in found)


def test_a_plan_that_says_no_product_fits_lets_the_close_go_unlinked():
    assert not sop.outline_plan(GOOD_OUTLINE)["no_product"]
    honest = GOOD_OUTLINE.replace(
        "Product: https://sdsmanager.com/us/ehs-software/.", "No registry product fits this gap honestly."
    )
    assert sop.outline_plan(honest)["no_product"]
    close = "## Keep Every SDS Where Your Auditor Can Find It"
    body = GOOD_DRAFT.split(close, 1)[1].split("\n## ", 1)[0]
    unlinked = GOOD_DRAFT.replace(body, "\n\nPaper binders go missing; list every product this week.\n")
    assert any("links no product page" in f for f in blocking(sop.check("draft", unlinked, CTX)))
    ctx = {**CTX, "no_product": True}
    assert not any("links no product page" in f for f in blocking(sop.check("draft", unlinked, ctx)))


# ---- Phase 3 (docs/sop-audit.md): one check profile per content type ----

GUEST = (
    "# Why UK Workplace Risk Registers Fail an HSE Inspection\n\n"
    "A register lists risks. Inspectors ask for the assessment behind each line, and a workplace risk "
    "assessment is what they judge. Keeping it current is what passes an inspection.\n\n"
    "## Why Registers Fail\n\nNobody owns the review dates. "
    "[EHS risk management software](https://sdsmanager.com/uk/ehs-software/risk-management-software/) "
    "gives every risk an owner and a review date.\n\n"
    "## What the Law Requires\n\nThe Management Regulations require a suitable and sufficient assessment. "
    "An employer with five or more employees records the significant findings and the groups at risk. "
    "The assessment covers everyone the work affects, including visitors and contractors on site.\n\n"
    "## How to Keep Assessments Current\n\nReview after any change to the work. A new machine, a new "
    "chemical or a reported near miss each starts a review of the lines it touches. Record the date of "
    "each review and who carried it out, so an inspector can follow the history of every risk.\n\n"
    "## Final Thoughts\n\nCheck one line of the register against the shop floor this week.\n"
)
GUEST_CTX = {
    **CTX,
    "content_type": "outbound",
    "pkeyword": "workplace risk assessment",
    "title": "Why UK workplace risk registers fail an HSE inspection",
    "anchors": [
        {
            "text": "EHS risk management software",
            "url": "https://sdsmanager.com/uk/ehs-software/risk-management-software/",
        }
    ],
}


def test_a_guest_post_follows_its_own_profile_not_the_blog_shape():
    found = blocking(sop.check("draft", GUEST, GUEST_CTX))
    assert not found, (
        found
    )  # no Key Takeaways, FAQ, scope sentence or CTA close required; title case-insensitive
    renamed = GUEST.replace("# Why UK Workplace Risk Registers Fail", "# Why Risk Registers Fail")
    assert any(
        "brief's title, kept word for word" in f for f in blocking(sop.check("draft", renamed, GUEST_CTX))
    )
    scoped = GUEST.replace(
        "A register lists risks.", "In this article, we look at registers. A register lists risks."
    )
    assert any("announces the article" in f for f in blocking(sop.check("draft", scoped, GUEST_CTX)))


def test_a_guest_post_links_only_its_anchors_and_none_in_the_close():
    extra = GUEST.replace(
        "Review after any change to the work.",
        "Review after any change, in [SDS software](https://sdsmanager.com/uk/).",
    )
    found = [f for f in sop.check("draft", extra, GUEST_CTX) if f.severity == "block"]
    off_brief = next(f for f in found if "aren't the brief's anchors" in f.text)
    assert off_brief.allows["drop_urls"] == ["https://sdsmanager.com/uk/"]
    closing = GUEST.replace(
        "this week.\n",
        "this week in [risk software](https://sdsmanager.com/uk/ehs-software/risk-management-software/).\n",
    ).replace(
        "[EHS risk management software](https://sdsmanager.com/uk/ehs-software/risk-management-software/)",
        "EHS risk management software",
    )
    assert any("sits in the close" in f for f in blocking(sop.check("draft", closing, GUEST_CTX)))


def test_a_guest_post_outline_needs_no_blog_components_but_keeps_the_title():
    outline = GOOD_OUTLINE
    headings = (
        "## Headings-Only Outline\nH1: Why UK workplace risk registers fail an HSE inspection\n"
        "H2: Why Registers Fail\nH2: What the Law Requires\nH2: How to Keep Assessments Current\n"
    )
    outline = re.sub(r"(?ms)^## Headings-Only Outline\n.*", headings, outline)
    found = blocking(sop.check("outline", outline, GUEST_CTX))
    assert not any("Key Takeaways" in f or "Frequently Asked" in f for f in found), found
    retitled = outline.replace("H1: Why UK workplace", "H1: Why workplace")
    assert any("brief's title" in f for f in blocking(sop.check("outline", retitled, GUEST_CTX)))


def test_every_prompt_renders_for_every_content_type(brief):
    for content_type in ("seo_blog", "outbound", "lead_magnet", "whitepaper"):
        brief.content_type = content_type
        brief.save()
        step = services.create_run(brief, {}).steps.get(key="draft")
        for name in ("outline", "draft", "sop_revise"):
            context = sop.prompting.context_for(step)
            text = "".join(m["content"] for m in sop.prompting.render(name, context))
            leftover = set(re.findall(r"\{\{(\w+)\}\}", text)) - {
                "findings",
                "length_rule",
                "link_sources",
                "previous_rejection",
                "output",
                "step_label",
            }
            assert not leftover, (content_type, name, leftover)
    guest = sop.prompting.type_structure("outbound")
    assert "brief's title, word for word" in guest["draft_structure"]
    assert "Key Takeaways" not in guest["draft_structure"].split("No Key Takeaways")[0]
    assert "this article" in sop.prompting.type_structure("seo_blog")["draft_structure"]


def test_localise_may_swap_regulators_and_region_links_but_marks_changed_figures():
    us = (
        "## Rules\n\nOSHA requires it under 1910.1200. "
        "See [EHS software](https://sdsmanager.com/us/ehs-software/). Keep it 30 years.\n"
    )
    uk = (
        "## Rules\n\nHSE requires it under COSHH. "
        "See [EHS software](https://sdsmanager.com/uk/ehs-software/). Keep it 30 years.\n"
    )
    assert sop._guard("localise", us, uk, swap=("us", "uk"))[0]
    assert not sop._guard("review_edit", us, uk)[0]  # the edit step keeps every fact
    changed = uk.replace("30 years", "40 years")
    assert not sop._guard("localise", us, changed, swap=("us", "uk"))[0]
    assert sop._guard("localise", us, changed.replace("40 years.", "40 years [VERIFY]."), swap=("us", "uk"))[
        0
    ]


def test_localise_is_not_checked_against_the_source_keyword(brief):
    brief.localise_to = "UK"
    brief.save()
    step = services.create_run(brief, {"localise": {"enabled": True}}).steps.get(key="localise")
    ctx = sop.context_from(step)
    assert ctx["pkeyword"] == "" and ctx["region"] == "UK"
    assert any("/uk/" in url for url in ctx["allowed_urls"])


def test_the_first_guest_post_anchor_must_sit_in_the_first_thirty_percent():
    anchor = (
        "[EHS risk management software](https://sdsmanager.com/uk/ehs-software/risk-management-software/)"
    )
    late = GUEST.replace(anchor, "EHS risk management software").replace(
        "Review after any change to the work.", f"Review after any change; {anchor} tracks it."
    )
    assert any("first 30%" in f for f in blocking(sop.check("draft", late, GUEST_CTX)))
    assert not any("first 30%" in f for f in blocking(sop.check("draft", GUEST, GUEST_CTX)))


# ---- Phase 4 (docs/sop-audit.md): mechanical fixes before any model round ----


def test_component_heading_variants_are_named_and_the_faq_fenced():
    text = (
        "# T\n\nIntro.\n\n## Key Points\n\n- One.\n\n## Body\n\nText.\n\n## FAQs\n\n### Q one?\n\nA one.\n\n"
        "### Q two?\n\nA two.\n\n## Sources\n\n1. OSHA.\n"
    )
    fixed, fixes = sop.normalise("draft", text)
    assert (
        "## Key Takeaways" in fixed and "## Frequently Asked Questions" in fixed and "## References" in fixed
    )
    assert ":::faq\n### Q one?" in fixed and fixed.count(":::") == 2
    assert fixes["component headings named"] == 3 and fixes["FAQ wrapped in :::faq"] == 1
    # A "Key Points" that isn't the first H2 is a normal section.
    later = text.replace("## Key Points", "## Overview").replace("## Body", "## Key Points")
    assert "## Key Points" in sop.normalise("draft", later)[0]


def test_sdsmanager_links_are_canonical_and_still_count_as_sourced():
    text = "See [EHS software](http://www.sdsmanager.com/us/ehs-software) and [SDS](https://sdsmanager.com/uk#top).\n"
    fixed, counts = sop.house.mechanical_fix(text)
    assert (
        "(https://sdsmanager.com/us/ehs-software/)" in fixed and "(https://sdsmanager.com/uk/#top)" in fixed
    )
    assert counts["sdsmanager.com links canonicalised"] == 2
    ctx = {**CTX, "allowed_urls": {"https://sdsmanager.com/us/ehs-software/", "https://sdsmanager.com/uk"}}
    assert not blocking(sop.check_sourced_urls(fixed, ctx))
    assert sop.house.mechanical_fix("[logo](https://sdsmanager.com/logo.svg)\n")[0].count("logo.svg)") == 1


def test_the_underline_placeholder_and_heading_anchors_are_handled():
    fixed, counts = sop.house.mechanical_fix("## Which Sections to Read First ++underlined text++\n")
    assert "underlined text" not in fixed and counts["underline placeholder"] == 1
    tagged = GOOD_DRAFT.replace(
        "## Do Safety Data Sheets Expire?", "## Do Safety Data Sheets Expire? {#expiry}"
    )
    assert not any("with a comma" in f or "{#" in f for f in blocking(sop.check("draft", tagged, CTX)))


def test_faq_answers_may_carry_links():
    linked = GOOD_DRAFT.replace(
        "even when a supplier hosts the sheets.",
        "even when a supplier hosts the [sheets](https://sdsmanager.com/us/ehs-software/).",
    )
    assert not any("FAQ answer" in f and "link" in f for f in blocking(sop.check("draft", linked, CTX)))


def test_metadata_heading_variants_are_split_off():
    from apps.studio import textclean

    for heading in ("## Metadata Options:", "## SEO Metadata", "## Metadata"):
        article, options = textclean.split_metadata(f"# T\n\nBody.\n\n{heading}\n\n### Slugs\n\n- my-slug\n")
        assert "Metadata" not in article and options == {"slug": ["my-slug"]}, heading


def test_heading_commas_become_colons_mechanically_but_not_in_the_title():
    text = (
        "# Worked Guide, Acetone\n\n## Worked Example, Acetone SDS\n\nText.\n\n"
        "### Managing 1,000 Chemicals, Fast\n\nText.\n\n"
        "## If an SDS Is Missing, What Should You Do?\n\nText.\n"
    )
    fixed, fixes = sop.normalise("draft", text)
    assert "## Worked Example: Acetone SDS" in fixed and "### Managing 1,000 Chemicals: Fast" in fixed
    assert "## If an SDS Is Missing, What Should You Do?" in fixed  # a question keeps its comma
    assert "# Worked Guide, Acetone" in fixed and fixes["heading commas made colons"] == 2


# ---- Phase 5 (docs/sop-audit.md): what the reviewer and the reviser are given ----


def test_the_reviewer_gets_blocks_and_prompts_as_two_lists_and_the_measurements(draft_step):
    comma = GOOD_DRAFT.replace("## Do Safety Data Sheets Expire?", "# Second Title")  # a block: two H1s
    call = ScriptedCall(["PASS"], [])
    sop.run_loop(draft_step, comma, call, max_rounds=0)
    context = call.sent[0][1]
    assert "2 H1 heading(s)" in context["checks"] and "[block]" not in context["checks"]
    assert "2 H1 heading(s)" not in context["prompts"]
    assert "article FKGL" in context["measurements"] and "words" in context["measurements"]
    target = sop.measurements("draft", GOOD_DRAFT, {**CTX, "fkgl": 9.0, "wordcount": 1200})
    assert "against a target of 9" in target and "against a guide of 1200" in target
    assert sop.measurements("outline", GOOD_DRAFT, CTX) == ""


def test_verdicts_parse_whatever_heading_style_the_reviewer_uses():
    verdict, findings, suggestions = sop.parse_verdict(
        "VERDICT: REVISE\n\n**Findings:**\n1. Intro · rule · fix\n2. None.\n\n**Suggestions**\n- Add a table"
    )
    assert verdict == "REVISE" and findings == ["Intro · rule · fix"] and suggestions == ["Add a table"]
    assert sop.parse_verdict("VERDICT: REVISE\n\n## Findings\n1. None.\n")[0] == "PASS"
    assert sop.parse_verdict("VERDICT: REVISE\n1. A heading · rule · fix\n")[1] == ["A heading · rule · fix"]


def test_a_strategic_reviewer_finding_holds_without_a_revision(draft_step):
    call = ScriptedCall([], [])
    call.verdicts = []
    original = call.__call__

    def reviewer(prompt_name, context, task):
        if prompt_name == "sop_review":
            call.sent.append((prompt_name, context))
            return "VERDICT: REVISE\n\n## Findings\n1. [strategic] The intent is commercial, not how-to.", "r"
        return original(prompt_name, context, task)

    result = sop.run_loop(draft_step, GOOD_DRAFT, reviewer, max_rounds=2)
    assert result.route == "hold" and "[strategic]" in result.routed[0]
    assert [name for name, _ in call.sent] == ["sop_review"]
    assert "strategic (reviewer)" in result.note()


def test_a_structural_reviewer_finding_sends_an_article_back(draft_step):
    sent = []

    def reviewer(prompt_name, context, task):
        sent.append(prompt_name)
        return "VERDICT: REVISE\n\n## Findings\n1. [structural] The section on archiving is missing.", "r"

    result = sop.run_loop(draft_step, GOOD_DRAFT, reviewer, max_rounds=2)
    assert result.route == "send_back" and sent == ["sop_review"]


def test_findings_hand_the_reviser_concrete_values():
    close = "## Keep Every SDS Where Your Auditor Can Find It"
    body = GOOD_DRAFT.split(close, 1)[1].split("\n## ", 1)[0]
    unlinked = GOOD_DRAFT.replace(body, "\n\nPaper binders go missing; list every product this week.\n")
    ctx = {**CTX, "planned_product": "https://sdsmanager.com/us/ehs-software/"}
    found = blocking(sop.check("draft", unlinked, ctx))
    assert any("links no product page" in f and "https://sdsmanager.com/us/ehs-software/" in f for f in found)
    assert sop.outline_plan(GOOD_OUTLINE)["planned_product"] == "https://sdsmanager.com/us/ehs-software/"
    cite = "## Rules\n\nTraining is required under 1910.1200(c)(1).\n"
    finding = blocking(sop.check_citations(cite, {**CTX, "allowed_citations": {"1910.1200(h)(1)"}}))[0]
    assert "for this standard: 1910.1200(h)(1)" in finding


def test_a_hold_note_leads_with_what_to_look_at():
    result = sop.SopResult(text="", passed=False)
    result.rounds.append(
        sop.Round(
            1,
            checks=[
                "[block] the link https://sdsmanager.com/x/ isn't in the inputs (invented URL); use …",
                "[block] the link https://sdsmanager.com/y/ isn't in the inputs (invented URL); use …",
                "[block] meta narration: 'In this section'",
            ],
            findings=["Intro · rule · fix"],
        )
    )
    note = result.note()
    assert "Look at first: 2× invented URL" in note
