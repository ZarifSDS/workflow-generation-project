from django import template
from django.utils.safestring import mark_safe

from apps.ai import catalog
from apps.content.markup import WagtailResolver, markdown_to_html

register = template.Library()


@register.filter
def render_markdown(text):
    """Step output as HTML for the admin: wagtail:// images, pages and documents are resolved."""
    return mark_safe(markdown_to_html(text, WagtailResolver()))  # noqa: S308 - sanitised by nh3


STATUS_STYLE = {
    "ready": "info",
    "needs_review": "info",
    "approved": "ok",
    "done": "ok",
    "queued": "neutral",
    "pending": "neutral",
    "running": "neutral",
    "skipped": "muted",
    "failed": "bad",
    "rejected": "bad",
}


@register.filter
def status_style(status):
    return STATUS_STYLE.get(status, "neutral")


@register.simple_tag
def model_label(provider, model):
    if not model:
        return "Default model"
    item = catalog.find(provider, model)
    if item:
        return f"{item.label} · {catalog.provider_label(provider)}"
    return f"{model} · {provider}"


@register.simple_tag
def sop_badge(step):
    """How the SOP self-review went for a step with it switched on, for the step timeline."""
    version = step.latest_version
    sop = (version.metrics or {}).get("sop") if version else None
    if not sop:
        return (
            "SOP self-review"
            if step.status in ("pending", "queued", "running", "skipped")
            else "SOP: no review"
        )
    rounds = len(sop.get("rounds") or [])
    if sop.get("passed"):
        return f"SOP passed ({rounds} round{'s' if rounds != 1 else ''})"
    if sop.get("error"):
        return "SOP: reviewer failed"
    return f"SOP held ({rounds} round{'s' if rounds != 1 else ''})"


@register.filter
def duration(seconds):
    return catalog.describe_duration(seconds)


@register.filter
def fkgl_width(value):
    """Bar width (%) for a grade on a 0–20 scale."""
    try:
        return max(4, min(100, round(float(value) / 20 * 100)))
    except (TypeError, ValueError):
        return 0


@register.filter
def fkgl_level(value, target):
    try:
        value, target = float(value), float(target)
    except (TypeError, ValueError):
        return "neutral"
    if value > 13:
        return "bad"
    if value > target + 1.5:
        return "warn"
    return "ok"


@register.filter
def get_item(mapping, key):
    return (mapping or {}).get(key)


@register.filter
def clock(seconds):
    """A stopwatch reading: 4:05, or 1:02:09 past an hour. The live timer in the run workspace uses it too."""
    if seconds is None:
        return ""
    seconds = max(0, int(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


@register.filter
def took(seconds):
    """How long something took, in words: 9 s, 4 min 05 s, 1 h 02 min."""
    if seconds is None or seconds == "":
        return ""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds} s"
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours} h {minutes:02d} min" if hours else f"{minutes} min {secs:02d} s"
