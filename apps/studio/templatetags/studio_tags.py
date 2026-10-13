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
