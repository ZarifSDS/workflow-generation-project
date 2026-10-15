"""What a run will take before it starts: time, money and whether each step fits its model's context window
(docs/pricing-and-ux-plan.md). Tokens per step come from the usage ledger of past runs once three runs of a
step are recorded; until then from conservative defaults. Prices come from apps.ai.pricing, so a free-tier,
subscription or local model costs nothing and a model without a known price is reported as unknown."""

import statistics
from decimal import Decimal

from apps.ai import pricing

# (input tokens, output tokens, largest single prompt) for one run of a step without the SOP self-review.
# The edit step makes several calls (deslop, clarity, up to ten tuning calls).
DEFAULT_TOKENS = {
    "site_crawl": (6000, 2000, 6000),
    "research": (9000, 5000, 9000),
    "outline": (14000, 6000, 14000),
    "draft": (20000, 9000, 20000),
    "review_edit": (60000, 30000, 16000),
    "localise": (14000, 8000, 14000),
    "hero_image": (4000, 2000, 4000),
}
SOP_TOKENS = (25000, 9000)  # two review rounds and a revision, on top of the step
DEFAULT_SECONDS = 60
MIN_MEASURED_RUNS = 3


def measured_tokens(step_key, limit=30):
    """(input, output, largest prompt, runs) from the ledger's last `limit` runs of a step, or None."""
    from apps.ai.models import UsageRecord

    rows = (
        UsageRecord.objects.filter(kind="step", step_key=step_key, run_id__isnull=False)
        .order_by("-pk")
        .values_list("run_id", "input_tokens", "output_tokens")[: limit * 20]
    )
    runs, largest = {}, 0
    for run_id, tokens_in, tokens_out in rows:
        total = runs.setdefault(run_id, [0, 0])
        total[0] += tokens_in or 0
        total[1] += tokens_out or 0
        largest = max(largest, tokens_in or 0)
    if len(runs) < MIN_MEASURED_RUNS:
        return None
    totals = list(runs.values())[:limit]
    return (
        round(statistics.median(t[0] for t in totals)),
        round(statistics.median(t[1] for t in totals)),
        largest,
        len(totals),
    )


def step_tokens(step_key, self_review=False):
    """{"input", "output", "largest", "measured"} for one run of a step."""
    measured = measured_tokens(step_key)
    if measured:
        tokens_in, tokens_out, largest, runs = measured
    else:
        tokens_in, tokens_out, largest = DEFAULT_TOKENS.get(step_key, (0, 0, 0))
        runs = 0
        if self_review and tokens_in:
            tokens_in, tokens_out = tokens_in + SOP_TOKENS[0], tokens_out + SOP_TOKENS[1]
    return {"input": tokens_in, "output": tokens_out, "largest": largest, "measured": runs}


def context_needed(step_key):
    """Tokens a step's largest call needs: its prompt plus the output it may write."""
    from .executors import MAX_TOKENS

    tokens = step_tokens(step_key)
    if not tokens["largest"]:
        return 0
    return tokens["largest"] + MAX_TOKENS.get(step_key, 8000)


def price_per_m(provider, model):
    """(input, output) USD per million tokens this key is billed, (0, 0) when free on this key, or None
    when the price is unknown."""
    if pricing.billing(provider) in (pricing.LOCAL, "free_tier", "subscription"):
        return Decimal("0"), Decimal("0")
    found = pricing.info(provider, model) or {}
    if found.get("in") is None or found.get("out") is None:
        return None
    return found["in"], found["out"]


def fits(provider, model, step_key, need=None, item=None):
    """False when the model's known context window is smaller than the step needs (`need`, if the caller
    already worked it out: it reads the ledger; `item`, the catalog entry, if the caller has it)."""
    need = context_needed(step_key) if need is None else need
    return not (need and (window := usable_context(provider, model, item=item)) and window < need)


def usable_context(provider, model, item=None):
    """The context a call really gets: the model's window, or less where the studio sets one (local
    Ollama models run with num_ctx, e.g. 32,768 of a 203k model)."""
    from apps.ai import catalog

    window = (pricing.info(provider, model) or {}).get("context")
    item = item or catalog.find(provider, model)
    set_ctx = (item.options or {}).get("num_ctx") if item else None
    if set_ctx and (not window or set_ctx < window):
        return set_ctx
    return window


def run_estimate(choices, seconds_for=None):
    """`choices`: [{"step", "provider", "model", "self_review"}] for the steps that will run.
    Returns {"seconds", "cost", "paid", "unknown", "too_small", "measured"}; cost is None when every
    priced step is unknown, and "unknown" names the models without a price."""
    seconds, cost, paid, unknown, too_small, measured = 0, Decimal("0"), set(), [], [], True
    for choice in choices:
        step, provider, model = choice["step"], choice.get("provider"), choice.get("model")
        if not model:
            continue
        if seconds_for:
            seconds += seconds_for(step, provider, model) or DEFAULT_SECONDS
        tokens = step_tokens(step, choice.get("self_review"))
        measured = measured and bool(tokens["measured"])
        if not fits(provider, model, step):
            too_small.append(step)
        price = price_per_m(provider, model)
        if price is None:
            unknown.append(f"{provider}::{model}")
            continue
        step_cost = (Decimal(tokens["input"]) * price[0] + Decimal(tokens["output"]) * price[1]) / 1_000_000
        if step_cost > 0:
            paid.add(f"{provider}::{model}")
        cost += step_cost
    return {
        "seconds": seconds,
        "cost": cost.quantize(Decimal("0.0001")),
        "paid": sorted(paid),
        "unknown": sorted(set(unknown)),
        "too_small": too_small,
        "measured": measured,
    }
