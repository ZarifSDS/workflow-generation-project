"""The default reader (owner's rule, 2026-10-14): anyone new to the topic, audience-agnostic headings and
angles, a standard and enjoyable informational tone, no persona. Query-matching question headings stay."""

import pytest

from apps.studio import prompting, services
from apps.studio.models import AudienceProfile, ContentBrief

pytestmark = pytest.mark.django_db


def _brief(admin_user, **fields):
    values = {
        "topic": "How long to keep SDSs",
        "pkeyword": "SDS retention requirements",
        "region": "US",
        "content_type": "seo_blog",
        "created_by": admin_user,
        **fields,
    }
    return ContentBrief.objects.create(**values)


def _prompt(brief, key="draft"):
    run = services.create_run(brief, {})
    messages = prompting.render(key, prompting.context_for(run.steps.get(key=key)))
    return messages[0]["content"], messages[1]["content"]


def test_a_new_brief_is_written_for_a_newcomer_by_default(admin_user):
    brief = _brief(admin_user)
    assert brief.comprehension == "beginner"
    system, user = _prompt(brief)
    assert "someone completely new to the topic, whatever their job" in system
    assert "No persona" in system
    assert "senior B2B writer" not in system
    assert "| Reader | anyone new to the topic, whatever their job (beginner (new to the topic)) |" in user
    # The skill's default STYLE_REFERENCE at beginner comprehension.
    assert "Style reference for a reader new to the topic" in user
    assert "Purpose before mechanism" in user


def test_headings_keep_their_query_form(admin_user):
    system, user = _prompt(_brief(admin_user), "outline")
    assert "leaning to the question form where people search that way" in system
    assert "Lean to question-form H2s" in user
    assert "not a job title, industry or seniority" in user


def test_a_brief_can_still_name_its_reader(admin_user):
    brief = _brief(admin_user, audience="Lab managers at universities", comprehension="practitioner")
    _, user = _prompt(brief)
    assert "| Reader | Lab managers at universities (practitioner) |" in user
    assert "Style reference for a reader new to the topic" not in user


def test_the_seeded_profiles_lost_their_personas():
    us = AudienceProfile.objects.get(region="US")
    assert us.audience == ""
    assert "B2B SaaS readers" not in us.style and us.style.endswith("Cite OSHA and the CFR.")
    assert us.prompt_block().startswith("Reader for US")
    assert "anyone new to the topic, whatever their job" in us.prompt_block()


def test_an_edited_profile_keeps_its_reader():
    profile = AudienceProfile(region="NZ", audience="Farm health and safety reps", style="Short.")
    assert "Reader for New Zealand (WorkSafe): Farm health and safety reps." in profile.prompt_block()
