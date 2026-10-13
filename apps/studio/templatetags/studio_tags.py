import markdown as md
import nh3
from django import template
from django.utils.safestring import mark_safe

from apps.ai import catalog

register = template.Library()

# Model output is untrusted: render Markdown, then allow only harmless tags. Raw HTML in the
# output is escaped by Markdown's own rules and stripped again by nh3.
ALLOWED_TAGS = {
    "p",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "ul",
    "ol",
    "li",
    "strong",
    "em",
    "code",
    "pre",
    "blockquote",
    "table",
    "thead",
    "tbody",
    "tr",
    "th",
    "td",
    "hr",
    "br",
    "a",
}


@register.filter
def render_markdown(text):
    html = md.markdown(text or "", extensions=["tables", "sane_lists"], output_format="html")
    cleaned = nh3.clean(
        html,
        tags=ALLOWED_TAGS,
        attributes={"a": {"href", "title"}},
        url_schemes={"http", "https", "mailto"},
        link_rel="noopener noreferrer nofollow",
    )
    return mark_safe(cleaned)  # noqa: S308 - sanitised by nh3 above


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
        return f"{item.label} · {catalog.PROVIDER_LABELS.get(provider, provider)}"
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
