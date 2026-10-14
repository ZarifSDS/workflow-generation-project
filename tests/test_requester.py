"""Research's "Questions for the Requester" as a form whose answers go into the research text."""

import pytest
from django.urls import reverse

from apps.studio import prompting, requester, services
from apps.studio.models import ContentBrief
from tests.test_studio import make_ready


@pytest.fixture
def brief(admin_user):
    return ContentBrief.objects.create(
        topic="How to read an SDS", pkeyword="how to read an sds", region="US", created_by=admin_user
    )


RESEARCH = """## Search Intent

Informational.

## Questions for the Requester

1. Should the article name a specific SDS software product? Assumed answer: Yes, the SDS Manager product page.
2. **Is the reader a supervisor or a worker?**
   *Assumed:* A supervisor at a small manufacturer.
3. Should state plans be covered?

## Cannibalization

No overlap.
"""


def test_numbered_questions_with_assumed_answers_are_read():
    questions = requester.parse(RESEARCH)
    assert [q["question"] for q in questions] == [
        "Should the article name a specific SDS software product?",
        "Is the reader a supervisor or a worker?",
        "Should state plans be covered?",
    ]
    assert questions[0]["assumed"] == "Yes, the SDS Manager product page."
    assert questions[1]["assumed"] == "A supervisor at a small manufacturer."
    assert questions[2]["assumed"] == ""


@pytest.mark.parametrize(
    "line,question,assumed",
    [  # shapes gpt-oss wrote in runs 17-21
        (
            "**Do you want a PDF cheat sheet?**, Assumed **yes** (matches the poster search).",
            "Do you want a PDF cheat sheet?",
            "yes (matches the poster search).",
        ),
        (
            "**Which chemical?** – assumed **Acetone** as a common example.",
            "Which chemical?",
            "Acetone as a common example.",
        ),
        (
            "**Is there a preferred CTA page?** (Assumed the main product page.)",
            "Is there a preferred CTA page?",
            "the main product page.",
        ),
        (
            "Should we add a table?, *Include a brief 2-row table.*",
            "Should we add a table?",
            "Include a brief 2-row table.",
        ),
        ("**Do you need a comparison table?** (body)", "Do you need a comparison table?", ""),
        (
            "**Should the CTA link a product page?**, Assuming a product page.",
            "Should the CTA link a product page?",
            "a product page.",
        ),
    ],
)
def test_the_shapes_models_write_are_split_into_question_and_assumption(line, question, assumed):
    (parsed,) = requester.parse(f"## Questions for the Requester\n\n1. {line}\n")
    assert (parsed["question"], parsed["assumed"]) == (question, assumed)


def test_a_table_and_none_are_read():
    table = (
        "## Questions for the Requester\n\n| # | Question | Assumed answer |\n|---|---|---|\n"
        "| 1 | Which region? | US |\n| 2 | Cover WHMIS? | No |\n"
    )
    assert [(q["question"], q["assumed"]) for q in requester.parse(table)] == [
        ("Which region?", "US"),
        ("Cover WHMIS?", "No"),
    ]
    assert requester.parse("## Questions for the Requester\n\nNone.\n") == []
    assert requester.parse("## Search Intent\n\nInformational.\n") == []


def test_answers_are_written_into_the_research_and_the_rest_is_kept():
    text = requester.apply_answers(
        RESEARCH, ["No, keep it brand-neutral until the close.", "", "Only Cal/OSHA."]
    )
    assert (
        "1. Should the article name a specific SDS software product?\n   Answer from the requester: No"
        in text
    )
    assert "2. Is the reader a supervisor or a worker?\n   Assumed answer: A supervisor" in text
    assert "3. Should state plans be covered?\n   Answer from the requester: Only Cal/OSHA." in text
    assert text.startswith("## Search Intent\n\nInformational.") and text.rstrip().endswith("No overlap.")
    again = requester.parse(text)
    assert again[0]["answered"] and not again[1]["answered"] and again[2]["answered"]
    with pytest.raises(ValueError):
        requester.apply_answers("## Search Intent\n\nx\n", ["a"])


def test_the_form_saves_a_version_the_next_steps_read(admin_client, brief):
    run = services.create_run(brief, {})
    research = make_ready(run.steps.get(key="research"), RESEARCH)
    url = reverse("studio:run", args=[run.pk]) + "?step=research"
    page = admin_client.get(url).content.decode()
    assert "Questions for you" in page and "A supervisor at a small manufacturer." in page
    response = admin_client.post(
        url,
        {
            "step": "research",
            "action": "answer_questions",
            "base_version": research.latest_version.number,
            "answer": ["No, keep it brand-neutral.", "A supervisor at a small manufacturer.", ""],
        },
        follow=True,
    )
    assert "Saved your answers as version 2" in response.content.decode()
    research.refresh_from_db()
    latest = research.latest_version
    assert latest.number == 2 and latest.source == "edit"
    assert "Answer from the requester: No, keep it brand-neutral." in latest.content
    services.approve_step(research, response.context["user"])
    assert "Answer from the requester: No, keep it brand-neutral." in prompting.approved_output(
        run, "research"
    )


def test_a_stale_form_is_refused(admin_client, brief):
    run = services.create_run(brief, {})
    research = make_ready(run.steps.get(key="research"), RESEARCH)
    url = reverse("studio:run", args=[run.pk]) + "?step=research"
    services.save_edit(research, None, RESEARCH.replace("Informational.", "Informational, how-to."))
    response = admin_client.post(
        url,
        {"step": "research", "action": "answer_questions", "base_version": 1, "answer": ["x", "y", "z"]},
        follow=True,
    )
    research.refresh_from_db()
    assert research.latest_version.number == 2  # nothing saved over the newer version
    assert "Saved your answers" not in response.content.decode()
