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
        anchors = "; ".join(f"“{a.get('text', '')}” → {a.get('url', '')}" for a in (brief.anchors or []))
        rows += [
            ("Target site", brief.site or brief.site_domain),
            ("Narrative mode", brief.get_narrative_mode_display() or "from the site profile"),
            ("Anchors (in order, each a different product page)", anchors or "none given"),
        ]
        if brief.source_reference:
            rows.append(("Brief source", brief.source_reference))
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
    kind = _types()[brief.content_type]
    context = {
        "rules": _template("_rules").strip(),
        "brief_table": brief_table(brief),
        "type_instructions": " ".join(kind["instructions"].split()),
        "publication": kind.get("publication", "an sdsmanager.com article"),
        "type_conclusion": " ".join(kind.get("conclusion", "").split()),
        "type_links": " ".join(kind.get("links", "").split()),
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
        **type_structure(brief.content_type),
    }
    context.update(extra or {})
    return context


# Prompt pieces that differ by content type (types.yaml); a type without one uses the blog's.
STRUCTURE_KEYS = (
    "heading_case",
    "keyword_rule",
    "h1_options",
    "outline_order",
    "intro_plan",
    "faq_plan",
    "headings_only",
    "draft_structure",
    "metadata",
)


def type_structure(content_type):
    types = _types()
    kind, blog = types[content_type], types["seo_blog"]
    values = {}
    for key in STRUCTURE_KEYS:
        value = kind.get(key) or blog.get(key, "")
        values[key] = value.strip() if key in ("draft_structure", "metadata") else " ".join(value.split())
    conclusion = " ".join(kind.get("conclusion", "").split())
    values["draft_structure"] = values["draft_structure"].replace("{{type_conclusion}}", conclusion)
    return values


def check_profile(content_type):
    """The check profile for a content type (types.yaml `checks`), over the blog's for missing keys."""
    types = _types()
    return {**types["seo_blog"].get("checks", {}), **(types.get(content_type, {}).get("checks") or {})}


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
