"""State changes for runs and steps. Views call these; M4's background tasks will too."""

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.ai import catalog
from apps.ai.evaluation import metrics as text_metrics

from .models import VERSIONS_TO_KEEP, GenerationRun, MetadataOption, StepRun, StepVersion
from .pipeline import steps_for


def default_model_for(step_def, profiles):
    """'provider::model' key for a step's default, from the AI profiles setting."""
    profile = profiles.get(step_def.profile or "") or {}
    if profile.get("provider") and profile.get("model"):
        return f"{profile['provider']}::{profile['model']}"
    return ""


@transaction.atomic
def create_run(brief, step_config, user=None):
    """step_config: {step_key: {"enabled": bool, "gate": bool, "model": "provider::model"}}."""
    run = GenerationRun.objects.create(brief=brief, created_by=user)
    first = True
    for order, step_def in enumerate(steps_for(brief.content_type)):
        config = step_config.get(step_def.key, {})
        enabled = config.get("enabled", step_def.default_on) if step_def.optional else True
        model_key = config.get("model") or default_model_for(step_def, settings.AI_PROFILES)
        provider, _, model = model_key.partition("::")
        status = StepRun.Status.SKIPPED
        if enabled:
            status = StepRun.Status.QUEUED if first else StepRun.Status.PENDING
            first = False
        StepRun.objects.create(
            run=run,
            key=step_def.key,
            order=order,
            enabled=enabled,
            gate=config.get("gate", step_def.gate),
            provider=provider,
            model=model,
            status=status,
        )
    return run


def _prune_versions(step):
    """Keep the first version and the last VERSIONS_TO_KEEP versions (docs/ux.md)."""
    numbers = list(step.versions.order_by("number").values_list("number", flat=True))
    keep = set(numbers[:1]) | set(numbers[-VERSIONS_TO_KEEP:])
    step.versions.exclude(number__in=keep).delete()


@transaction.atomic
def add_version(
    step, content, *, provider="", model="", source=StepVersion.Source.AI, user=None, note="", image=None
):
    last = step.versions.order_by("-number").first()
    computed = text_metrics.compute(content, step.run.brief.as_prompt_dict()) if content.strip() else {}
    version = StepVersion.objects.create(
        step=step,
        number=(last.number + 1) if last else 1,
        source=source,
        provider=provider,
        model=model,
        content=content,
        image=image,
        metrics=computed,
        note=note,
        created_by=user,
    )
    _prune_versions(step)
    return version


def _next_enabled(step):
    return step.run.steps.filter(enabled=True, order__gt=step.order).order_by("order").first()


def refresh_run_status(run):
    statuses = set(run.enabled_steps.values_list("status", flat=True))
    if run.status == GenerationRun.Status.REJECTED:
        return run
    if StepRun.Status.READY in statuses:
        run.status = GenerationRun.Status.NEEDS_REVIEW
    elif StepRun.Status.FAILED in statuses:
        run.status = GenerationRun.Status.FAILED
    elif StepRun.Status.RUNNING in statuses:
        run.status = GenerationRun.Status.RUNNING
    elif statuses <= {StepRun.Status.APPROVED, StepRun.Status.SKIPPED}:
        run.status = GenerationRun.Status.DONE
    else:
        run.status = GenerationRun.Status.QUEUED
    run.save(update_fields=["status", "updated_at"])
    return run


@transaction.atomic
def approve_step(step, user, edited_content=None):
    if step.status != StepRun.Status.READY:
        raise ValueError("Only a step that is ready for review can be approved.")
    latest = step.latest_version
    if edited_content is not None and latest and edited_content.strip() != latest.content.strip():
        add_version(
            step,
            edited_content,
            source=StepVersion.Source.EDIT,
            user=user,
            provider=latest.provider,
            model=latest.model,
        )
    step.status = StepRun.Status.APPROVED
    step.approved_by, step.approved_at = user, timezone.now()
    step.save()
    following = _next_enabled(step)
    if following and following.status == StepRun.Status.PENDING:
        following.status = StepRun.Status.QUEUED
        following.save(update_fields=["status"])
    return refresh_run_status(step.run)


@transaction.atomic
def reject_run(run, user, reason):
    run.status = GenerationRun.Status.REJECTED
    run.reject_reason = reason
    run.save(update_fields=["status", "reject_reason", "updated_at"])
    run.steps.filter(status=StepRun.Status.READY).update(status=StepRun.Status.REJECTED)
    return run


@transaction.atomic
def request_regenerate(step, model_key, note=""):
    """Queue the step again with a chosen model. M4's worker picks queued steps up."""
    choice = catalog.by_key(model_key)
    if choice is None or not choice.selectable:
        raise ValueError("Choose a model that is available.")
    step.provider, step.model = choice.provider, choice.model
    step.regenerate_note = note
    step.status = StepRun.Status.QUEUED
    step.error = ""
    step.save()
    return refresh_run_status(step.run)


def review_count():
    """Steps waiting for a decision, shown as the sidebar badge."""
    return StepRun.objects.filter(
        status=StepRun.Status.READY, run__status__in=[GenerationRun.Status.NEEDS_REVIEW]
    ).count()


# ---- Title, meta description and slug options ----


@transaction.atomic
def set_metadata_selection(run, selected_ids):
    options = run.metadata_options.all()
    for option in options:
        option.selected = option.pk in selected_ids
    MetadataOption.objects.bulk_update(options, ["selected"])


def add_own_metadata(run, kind, text):
    text = " ".join(text.split())
    if not text:
        raise ValueError("Type an option before adding it.")
    return MetadataOption.objects.create(
        run=run, kind=kind, text=text, source=StepVersion.Source.EDIT, selected=True
    )
