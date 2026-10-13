"""Background execution of pipeline steps (run by the `worker` container's db_worker)."""

import logging

from django.db import transaction
from django.tasks import task
from django.utils import timezone

from apps.ai.types import ProviderError

from .models import StepRun

logger = logging.getLogger(__name__)


@task()
def run_step(step_id):
    execute_step(step_id)


def execute_step(step_id):
    """Run one queued step. Safe to call twice: only a QUEUED step is picked up."""
    from . import executors, services

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
        output = executors.EXECUTORS[step.key](step)
    except (ProviderError, executors.StepError) as error:
        _fail(step, executors.friendly_error(error))
        return
    except Exception as error:  # noqa: BLE001 - never leave a step stuck in "running"
        logger.exception("Step %s (%s) crashed", step.pk, step.key)
        _fail(step, f"Unexpected error: {error!r}"[:1000])
        return

    services.add_version(
        step,
        output.content,
        provider=output.provider,
        model=output.model,
        note=output.note,
        image=output.image,
        extra_metrics=output.extra_metrics,
    )
    step.refresh_from_db()
    step.finished_at, step.regenerate_note = timezone.now(), ""
    if step.gate:
        step.status = StepRun.Status.READY
        step.save(update_fields=["status", "finished_at", "regenerate_note"])
        services.refresh_run_status(step.run)
    else:
        step.status, step.approved_at = StepRun.Status.APPROVED, timezone.now()
        step.save(update_fields=["status", "finished_at", "regenerate_note", "approved_at"])
        services.queue_next(step)


def _fail(step, message):
    from . import services

    step.status, step.error, step.finished_at = StepRun.Status.FAILED, message, timezone.now()
    step.save(update_fields=["status", "error", "finished_at"])
    services.refresh_run_status(step.run)
