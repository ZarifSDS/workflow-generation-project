"""Who may do what in Content Studio (M8). The groups that hold these permissions are created by
migration 0004 and can be adjusted in Wagtail under Settings › Groups. Superusers may do everything.

| Group     | Permissions |
|-----------|-------------|
| Writers   | access, writing steps (site crawl, research, outline, draft, title and meta), briefs and runs |
| Editors   | everything writers have, plus editing steps (review and edit to publish) and exports |
| Moderators| access (read-only); they publish pages through Wagtail's workflow |
| Operators | access, operate (models and providers, presets, recovering stuck steps) |
"""

ACCESS = "studio.access_studio"
WRITING = "studio.review_writing_steps"
EDITING = "studio.review_editing_steps"
OPERATE = "studio.operate_studio"

PERMISSIONS = [
    ("access_studio", "Can use Content Studio"),
    ("review_writing_steps", "Can review writing steps (site crawl to draft) and title and meta"),
    ("review_editing_steps", "Can review editing steps: review and edit to publish, and export"),
    ("operate_studio", "Can manage models, providers and presets, and recover stuck steps"),
]

WRITING_STEPS = {"site_crawl", "research", "outline", "draft"}


def step_permission(step_key):
    return WRITING if step_key in WRITING_STEPS else EDITING


def can_review(user, step):
    return user.has_perm(step_permission(step.key))


def can_start_runs(user):
    return user.has_perm(WRITING)


def can_act(user, step, action):
    """Whether `user` may take a run-workspace `action` on `step`."""
    if action == "recover":
        return user.has_perm(OPERATE)
    if action == "retry":
        return can_review(user, step) or user.has_perm(OPERATE)
    return can_review(user, step)


def describe_role(step):
    return "writers and editors" if step.key in WRITING_STEPS else "editors"
