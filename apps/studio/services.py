"""State changes for runs and steps. Views and the background task call these."""

import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.ai import catalog
from apps.ai.evaluation import metrics as text_metrics
from apps.content.markup import strip_dialect
from apps.quality import review as quality_review
from apps.quality import scans as quality_scans

from .models import VERSIONS_TO_KEEP, GenerationRun, MetadataOption, StepRun, StepVersion
from .pipeline import steps_for

logger = logging.getLogger(__name__)


def enqueue(step):
    """Hand a queued step to the worker once the surrounding transaction commits."""
    if not getattr(settings, "STUDIO_EXECUTE_STEPS", False):
        return
    from .tasks import run_step

    step_id = step.pk
    transaction.on_commit(lambda: run_step.enqueue(step_id))


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
    queued = None
    for order, step_def in enumerate(steps_for(brief.content_type)):
        config = step_config.get(step_def.key, {})
        enabled = config.get("enabled", step_def.default_on) if step_def.optional else True
        model_key = config.get("model") or default_model_for(step_def, settings.AI_PROFILES)
        provider, _, model = model_key.partition("::")
        status = StepRun.Status.SKIPPED
        if enabled:
            status = StepRun.Status.QUEUED if first else StepRun.Status.PENDING
            first = False
        created = StepRun.objects.create(
            run=run,
            key=step_def.key,
            order=order,
            enabled=enabled,
            gate=config.get("gate", step_def.gate),
            provider=provider,
            model=model,
            status=status,
        )
        if status == StepRun.Status.QUEUED:
            queued = created
    if queued:
        enqueue(queued)
    return run


def _prune_versions(step):
    """Keep the first version and the last VERSIONS_TO_KEEP versions (docs/ux.md)."""
    numbers = list(step.versions.order_by("number").values_list("number", flat=True))
    keep = set(numbers[:1]) | set(numbers[-VERSIONS_TO_KEEP:])
    step.versions.exclude(number__in=keep).delete()


QUALITY_SCAN_STEPS = {"draft", "review_edit", "cleanup", "localise"}


def _safe_metrics(content, step):
    """Checks for the checks panel. They're advisory: if one fails, the output is still saved."""
    if not content.strip():
        return {}
    computed = {}
    try:
        computed = text_metrics.compute(strip_dialect(content), step.run.brief.as_prompt_dict())
    except Exception as error:  # noqa: BLE001 - a broken metric must not lose a 20-minute generation
        logger.exception("Metrics failed for step %s", step.pk)
        computed["metrics_error"] = f"{error.__class__.__name__}: {str(error)[:200]}"
    if step.key in QUALITY_SCAN_STEPS and getattr(settings, "STUDIO_QUALITY_SCANS", True):
        try:
            computed["quality"] = quality_scans.summary(content)
        except Exception as error:  # noqa: BLE001
            logger.exception("Quality scans failed for step %s", step.pk)
            computed["quality_error"] = f"{error.__class__.__name__}: {str(error)[:200]}"
    return computed


@transaction.atomic
def add_version(
    step,
    content,
    *,
    provider="",
    model="",
    source=StepVersion.Source.AI,
    user=None,
    note="",
    image=None,
    extra_metrics=None,
):
    last = step.versions.order_by("-number").first()
    computed = _safe_metrics(content, step)
    computed.update(extra_metrics or {})
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
    return queue_next(step)


def queue_next(step):
    """After a step is approved (by you or automatically), queue the next enabled step."""
    following = _next_enabled(step)
    if following and following.status == StepRun.Status.PENDING:
        following.status = StepRun.Status.QUEUED
        following.save(update_fields=["status"])
        enqueue(following)
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
    step.notified_at = None
    step.save()
    enqueue(step)
    return refresh_run_status(step.run)


@transaction.atomic
def rerun_step(step):
    """Run a step without a model (e.g. Final cleanup, Publish) again, e.g. after changing the metadata."""
    if step.definition.profile or step.status != StepRun.Status.READY:
        raise ValueError("Only a step without a model that is waiting for review can be run again.")
    step.status, step.error, step.notified_at = StepRun.Status.QUEUED, "", None
    step.save(update_fields=["status", "error", "notified_at"])
    enqueue(step)
    return refresh_run_status(step.run)


@transaction.atomic
def recover_step(step, user=None, reason=""):
    """Mark a step stuck in "running" (its worker stopped) as failed, so it can be retried."""
    step.refresh_from_db()
    if step.status != StepRun.Status.RUNNING:
        raise ValueError("Only a running step can be marked as failed.")
    who = f" by {user.get_username()}" if user else ""
    step.status = StepRun.Status.FAILED
    step.error = reason or f"Marked as failed{who}: the worker stopped before the step finished. Retry it."
    step.finished_at = timezone.now()
    step.save(update_fields=["status", "error", "finished_at"])
    return refresh_run_status(step.run)


@transaction.atomic
def retry_step(step):
    """Queue a failed step again with the same model."""
    if step.status != StepRun.Status.FAILED:
        raise ValueError("Only a failed step can be retried.")
    step.status, step.error = StepRun.Status.QUEUED, ""
    step.save(update_fields=["status", "error"])
    enqueue(step)
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


@transaction.atomic
def accept_splits(step, user, accepted_ids):
    """Apply chosen split proposals as a new version (your edit); unaccepted ones stay proposals."""
    latest = step.latest_version
    review = (latest.metrics or {}).get("review") if latest else None
    if not review or not review.get("proposals"):
        raise ValueError("There are no split proposals on this version.")
    accepted = [p for p in review["proposals"] if p["id"] in accepted_ids]
    if not accepted:
        raise ValueError("Tick at least one split to apply.")
    text = quality_review.apply_splits(latest.content, review["proposals"], set(accepted_ids))
    remaining = [p for p in review["proposals"] if p["id"] not in accepted_ids]
    kept = {**review, "proposals": remaining, "accepted": review.get("accepted", []) + accepted}
    return add_version(
        step,
        text,
        source=StepVersion.Source.EDIT,
        user=user,
        provider=latest.provider,
        model=latest.model,
        note=latest.note,
        extra_metrics={"review": kept},
    )
