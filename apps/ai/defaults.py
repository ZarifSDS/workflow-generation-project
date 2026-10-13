"""Default model per task: what an admin chose under Settings › Default models, over settings.AI_PROFILES.

A task is a pipeline step with a model (research, outline, ...) or a sub-task of one (the hero image's
prompt and vision check); apps.studio.pipeline.MODEL_TASKS lists them with their built-in profile.
`resolve()` returns a profile-shaped dict ({"provider", "model", "options", "fallback"}) so callers that
used settings.AI_PROFILES[name] can switch without other changes.
"""

from django.conf import settings

from . import catalog

CACHE_KEY = "ai:task-defaults"
CACHE_SECONDS = 30


def overrides():
    """{task: (model_key, fallback_key)} chosen in the admin; cached briefly, cleared on save."""
    from django.core.cache import cache
    from django.db import DatabaseError

    from .models import TaskDefault

    cached = cache.get(CACHE_KEY)
    if cached is not None:
        return cached
    try:
        rows = {row.task: (row.model_key, row.fallback_key) for row in TaskDefault.objects.all()}
    except DatabaseError:
        return {}
    cache.set(CACHE_KEY, rows, CACHE_SECONDS)
    return rows


def clear_cache():
    from django.core.cache import cache

    cache.delete(CACHE_KEY)


def _target(key):
    provider, _, model = key.partition("::")
    item = catalog.find(provider, model)
    return {"provider": provider, "model": model, "options": dict(item.options or {}) if item else {}}


def built_in(profile_name):
    return dict(settings.AI_PROFILES.get(profile_name or "", {}))


def resolve(task, profile_name):
    """The profile for `task`: the built-in profile `profile_name`, with the admin's choices on top."""
    profile = built_in(profile_name)
    model_key, fallback_key = overrides().get(task, ("", ""))
    if model_key:
        fallback = profile.get("fallback")
        profile = _target(model_key)
        if fallback:
            profile["fallback"] = fallback
    if fallback_key:
        profile["fallback"] = _target(fallback_key)
    return profile


def model_key(profile):
    if profile.get("provider") and profile.get("model"):
        return f"{profile['provider']}::{profile['model']}"
    return ""
