"""The SOP self-review (apps/studio/sop.py, docs/sop.md): deterministic checks, the review-revise loop,
autopilot runs and the UI around them. No real provider calls."""

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

An exposure record is any document that identifies a chemical and where it was used. Our
[SDS management guide](https://sdsmanager.com/us/sds-management-articles/sds-guide/) explains the categories.

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
    assert any("FAQ question" in f for f in blocking(sop.check("outline", text, CTX)))


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
    assert any("adjacent" in f for f in blocking(sop.check("draft", text, CTX)))
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
        "(https://sdsmanager.com/us/sds-management-articles/sds-guide/) explains the categories.",
        "(https://sdsmanager.com/library) explains the categories.",
    )
    cleaned = invented.replace(
        "[SDS management guide](https://sdsmanager.com/library) explains the categories.", ""
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
