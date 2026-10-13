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


@dataclass(frozen=True)
class ModelTask:
    """A task with a default model, set under Settings › Default models (apps.ai.defaults)."""

    key: str
    label: str
    profile: str  # built-in profile in settings.AI_PROFILES
    kind: str = "text"
    help: str = ""


# Every step with a model, plus the two model calls inside the hero image step.
MODEL_TASKS = [
    *[ModelTask(s.key, s.label, s.profile, s.kind) for s in STEPS.values() if s.profile],
    ModelTask("hero_prompt", "Hero image prompt", "fast", help="Writes the photo prompt for the hero image."),
    ModelTask(
        "vision",
        "Hero image check",
        "vision",
        help="Looks at the generated photo. Needs a model that can read images, such as Gemini.",
    ),
]
MODEL_TASK_KEYS = {task.key: task for task in MODEL_TASKS}


def profile_for(task_key):
    """The model settings for a step or sub-task: the admin's default, else the built-in profile."""
    from apps.ai import defaults

    task = MODEL_TASK_KEYS.get(task_key)
    return defaults.resolve(task_key, task.profile if task else None) if task else {}
