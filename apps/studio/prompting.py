"""Render step prompts from apps/studio/prompts/*.md with the brief and earlier approved outputs."""

from functools import cache
from pathlib import Path

import yaml

from . import houseref
from .models import AudienceProfile, StepRun

PROMPTS_DIR = Path(__file__).parent / "prompts"


@cache
def _types():
    return yaml.safe_load((PROMPTS_DIR / "types.yaml").read_text(encoding="utf-8"))


@cache
def _template(name):
    return (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8")


def approved_output(run, key):
    """Latest version of an approved (or auto-continued) earlier step, or ''."""
    step = run.steps.filter(key=key, status=StepRun.Status.APPROVED).first()
    version = step.latest_version if step else None
    return version.content if version else ""


def brief_table(brief):
    rows = [
        ("Content type", _types()[brief.content_type]["label"]),
        ("Topic", brief.topic),
        ("Primary keyword", brief.pkeyword),
        ("Secondary keyword(s)", ", ".join(brief.skeywords or []) or "none"),
        (
            "Target word count",
            f"{brief.wordcount} (a guide: don't pad, don't cut needed content)"
            if brief.wordcount
            else "set by the topic",
        ),
        ("Target reading grade (FKGL)", f"{brief.fkgl} (soft target)"),
        ("Audience", f"{brief.audience or 'not specified'} ({brief.get_comprehension_display().lower()})"),
        ("Region", brief.get_region_display()),
    ]
    if brief.content_type == "outbound":
        rows += [
            ("Target site", brief.site or brief.site_domain),
            ("Narrative mode", brief.get_narrative_mode_display() or "from the site profile"),
        ]
    else:
        rows.append(("Call to action", brief.get_cta_style_display()))
    lines = ["| Field | Value |", "|---|---|"] + [f"| {label} | {value} |" for label, value in rows]
    return "\n".join(lines)


def audience_block(brief):
    """The region's audience profile (Settings › Audience profiles); the brief's own audience wins."""
    profile = AudienceProfile.objects.filter(region=brief.region).first()
    if not profile:
        return ""
    block = profile.prompt_block()
    if brief.audience:
        block += f"\nThis brief narrows the audience to: {brief.audience}."
    return f"\n{block}\n"


def _serp_block(report):
    if not report:
        return ""
    return (
        "\nWhat currently ranks for the primary keyword in this region (live search results and the "
        "structure of the top pages). Cover what searchers clearly expect, match the depth of the ranking "
        "pages, and beat them on clarity and accuracy; don't copy their wording:\n\n"
        f"{report}\n"
    )


def context_for(step, extra=None):
    run, brief = step.run, step.run.brief
    site_profile = approved_output(run, "site_crawl")
    note = (step.regenerate_note or "").strip()
    context = {
        "rules": _template("_rules").strip(),
        "brief_table": brief_table(brief),
        "type_instructions": " ".join(_types()[brief.content_type]["instructions"].split()),
        "topic": brief.topic,
        "pkeyword": brief.pkeyword,
        "fkgl": brief.fkgl,
        "region": brief.get_region_display(),
        "localise_to": brief.get_localise_to_display() if brief.localise_to else "",
        "notes": " ".join((brief.notes or "none").split()),
        "site": brief.site or brief.site_domain,
        "site_domain": brief.site_domain,
        "site_profile_block": f"\nApproved site profile of the target site:\n\n{site_profile}\n"
        if site_profile
        else "",
        "research": approved_output(run, "research") or "(no research step in this run)",
        "serp_block": _serp_block(approved_output(run, "search_results")),
        "audience_block": audience_block(brief),
        "outline": approved_output(run, "outline"),
        "draft": approved_output(run, "review_edit") or approved_output(run, "draft"),
        "related_articles": houseref.related_articles_block(brief),
        "product_pages": houseref.product_pages_block(brief.region),
        "regenerate_block": f"\nInstruction from the editor for this attempt: {note}\n" if note else "",
    }
    context.update(extra or {})
    return context


def render(name, context):
    """Return chat messages from a template with '## system' and '## user' sections."""
    text = _template(name)
    for key, value in context.items():
        text = text.replace("{{" + key + "}}", str(value))
    system, _, user = text.partition("## user")
    return [
        {"role": "system", "content": system.replace("## system", "", 1).strip()},
        {"role": "user", "content": user.strip()},
    ]
