"""The usage ledger: one UsageRecord per model call, with its tokens and cost (docs/pricing-and-ux-plan.md).

`apps.ai.service.generate` and `generate_image` call `record` after every successful call. What the call
belongs to (a run's step, a chat message, an image plan) comes from `scope`, which the worker tasks set
around their work, so no caller has to pass it along. Recording never raises: a ledger problem can't fail
a step.
"""

import contextvars
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

_scope = contextvars.ContextVar("ai_usage_scope", default=None)


@contextmanager
def scope(kind, run_id=None, step_key="", object_id=None):
    """Mark the model calls made inside the block as belonging to this run, step, chat or job."""
    token = _scope.set({"kind": kind, "run_id": run_id, "step_key": step_key, "object_id": object_id})
    try:
        yield
    finally:
        _scope.reset(token)


def record(result):
    """Write the ledger row for a GenerationResult or an ImageResult; returns it, or None when it couldn't
    be written."""
    from . import pricing
    from .models import UsageRecord
    from .types import ImageResult

    try:
        where = _scope.get() or {}
        stats = result.stats or {}
        image = isinstance(result, ImageResult)
        input_tokens = stats.get("input_tokens") if image else result.input_tokens
        output_tokens = stats.get("output_tokens") if image else result.output_tokens
        amount, kind = pricing.cost(
            result.provider,
            result.model,
            input_tokens,
            output_tokens,
            billed=stats.get("billed_cost"),
            images=1 if image else 0,
        )
        return UsageRecord.objects.create(
            provider=result.provider,
            model=result.model[:200],
            kind=where.get("kind") or "other",
            run_id=where.get("run_id"),
            step_key=where.get("step_key") or "",
            object_id=where.get("object_id"),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=amount,
            cost_kind=kind,
            seconds=result.total_time,
        )
    except Exception:  # noqa: BLE001 - the ledger is an extra: never fail the call it records
        logger.exception("Couldn't record usage for %s/%s", result.provider, result.model)
        return None


def totals(records):
    """{input, output, cost, calls, kinds} for an iterable of UsageRecord (or a queryset)."""
    from decimal import Decimal

    total = {"input": 0, "output": 0, "cost": Decimal("0"), "calls": 0, "kinds": set()}
    for row in records:
        total["input"] += row.input_tokens or 0
        total["output"] += row.output_tokens or 0
        total["cost"] += row.cost or 0
        total["calls"] += 1
        total["kinds"].add(row.cost_kind)
    total["exact"] = total["kinds"] <= {"billed", "free"}
    total["unknown"] = "unknown" in total["kinds"]
    return total


def for_run(run_id):
    """{step_key: totals} and the run's total."""
    from .models import UsageRecord

    rows = list(UsageRecord.objects.filter(run_id=run_id))
    steps = {}
    for row in rows:
        steps.setdefault(row.step_key or "other", []).append(row)
    return {key: totals(items) for key, items in steps.items()}, totals(rows)
