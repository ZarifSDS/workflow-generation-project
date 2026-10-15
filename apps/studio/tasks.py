"""Background execution of pipeline steps (run by the `worker` container's db_worker)."""

import logging

from django.db import transaction
from django.tasks import task
from django.utils import timezone

from apps.ai import usage
from apps.ai.redact import redact
from apps.ai.types import ProviderError

from .models import StepRun

logger = logging.getLogger(__name__)


@task()
def run_step(step_id):
    execute_step(step_id)


@task()
def run_chat(message_id):
    """Answer one suggestions-chat message or Tune request (apps/studio/assistant.py)."""
    from . import assistant
    from .models import ChatMessage

    message = ChatMessage.objects.filter(pk=message_id).select_related("step").first()
    step = message.step if message else None
    with usage.scope(
        "chat", run_id=step.run_id if step else None, step_key=step.key if step else "", object_id=message_id
    ):
        assistant.answer(message_id)


@task()
def run_image_job(job_id):
    """Make one image for the standalone Image generator (apps/studio/imagegen.py)."""
    from . import imagegen

    with usage.scope("image_job", object_id=job_id):
        imagegen.execute(job_id)


@task()
def run_image_plan(plan_id):
    """Read an existing article and propose images tailored to it (apps/studio/imagegen.py)."""
    from . import imagegen

    with usage.scope("image_plan", object_id=plan_id):
        imagegen.execute_plan(plan_id)


@task()
def sync_model_lists(names=None):
    """Read the providers' model lists into the studio's model dropdowns (apps/ai/remote_models.py)."""
    from apps.ai import remote_models

    remote_models.sync_all(names)


def execute_step(step_id):
    """Run one queued step. Safe to call twice: only a QUEUED step is picked up."""
    from . import executors, services, sop

    with transaction.atomic():
        step = StepRun.objects.select_for_update().select_related("run__brief").get(pk=step_id)
        if step.status != StepRun.Status.QUEUED:
            return
        step.status, step.started_at, step.finished_at, step.error = (
            StepRun.Status.RUNNING,
            timezone.now(),
            None,
            "",
        )
        step.save(update_fields=["status", "started_at", "finished_at", "error"])
    services.refresh_run_status(step.run)

    try:
        # Every model call inside (the step, its SOP rounds, the edit sequence) is logged to this step.
        with usage.scope("step", run_id=step.run_id, step_key=step.key, object_id=step.pk):
            output = executors.EXECUTORS[step.key](step)
            if step.self_review and step.key in sop.STEPS:
                # The SOP loop never fails a step: a reviewer problem holds the step with the output kept.
                output = sop.apply(step, output)
    except (ProviderError, executors.StepError) as error:
        _fail(step, executors.friendly_error(error))
        return
    except Exception as error:  # noqa: BLE001 - never leave a step stuck in "running"
        logger.exception("Step %s (%s) crashed", step.pk, step.key)
        _fail(step, f"Unexpected error: {error!r}"[:1000])
        return

    try:
        services.add_version(
            step,
            output.content,
            provider=output.provider,
            model=output.model,
            note=output.note,
            image=output.image,
            extra_metrics={
                **(output.extra_metrics or {}),
                "duration_seconds": round((timezone.now() - step.started_at).total_seconds()),
            },
        )
    except Exception as error:  # noqa: BLE001 - saving must never leave a step stuck in "running"
        logger.exception("Step %s (%s): saving the output failed", step.pk, step.key)
        _fail(step, f"The output was generated but couldn't be saved: {error!r}"[:1000])
        return
    step.refresh_from_db()
    step.finished_at, step.regenerate_note = timezone.now(), ""
    if step.gate or output.hold:
        step.status = StepRun.Status.READY
        step.save(update_fields=["status", "finished_at", "regenerate_note"])
        services.refresh_run_status(step.run)
    else:
        step.status, step.approved_at = StepRun.Status.APPROVED, timezone.now()
        step.save(update_fields=["status", "finished_at", "regenerate_note", "approved_at"])
        services.queue_next(step)


def _fail(step, message):
    from . import services

    step.status, step.error, step.finished_at = StepRun.Status.FAILED, redact(message), timezone.now()
    step.save(update_fields=["status", "error", "finished_at"])
    services.refresh_run_status(step.run)
