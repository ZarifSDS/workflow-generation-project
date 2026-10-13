"""Pipeline step definitions per content type (docs/workflow.md).

Kept in code rather than the database so the pipeline is versioned with the prompts and tests.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class StepDef:
    key: str
    label: str
    profile: str | None  # AI profile used by default; None for deterministic steps
    kind: str = "text"  # "text" | "image" | "none"
    gate: bool = True  # waits for your approval by default
    optional: bool = False  # can be switched off in the wizard
    default_on: bool = True


STEPS = {
    "site_crawl": StepDef("site_crawl", "Site crawl", "fast"),
    "research": StepDef("research", "Research", "fast"),
    "outline": StepDef("outline", "Outline", "quality"),
    "draft": StepDef("draft", "Draft", "quality"),
    "review_edit": StepDef("review_edit", "Review and edit", "edit"),
    "cleanup": StepDef("cleanup", "Final cleanup", None, kind="none", gate=False),
    "hero_image": StepDef("hero_image", "Hero image", "image", kind="image", optional=True),
    "localise": StepDef("localise", "Localise", "quality", optional=True, default_on=False),
    "publish": StepDef("publish", "Publish", None, kind="none"),
}

_ARTICLE = ["research", "outline", "draft", "review_edit", "cleanup", "hero_image", "localise", "publish"]

PIPELINES = {
    "seo_blog": _ARTICLE,
    "pillar": _ARTICLE,
    "whitepaper": _ARTICLE,
    "outbound": [
        "site_crawl",
        "research",
        "outline",
        "draft",
        "review_edit",
        "cleanup",
        "hero_image",
        "publish",
    ],
    "lead_magnet": ["research", "outline", "draft", "review_edit", "cleanup", "hero_image", "publish"],
}


def steps_for(content_type):
    return [STEPS[key] for key in PIPELINES[content_type]]
