"""What each pipeline step does when the worker runs it. Each executor returns a StepOutput."""

import io
import re
from dataclasses import dataclass, field

import textstat
from django.conf import settings
from django.core.files.images import ImageFile

from apps.ai import catalog
from apps.ai.service import generate, generate_image
from apps.ai.types import ProviderError
from apps.quality import review
from apps.quality import scripts as quality_scripts

from . import prompting, textclean, webfetch
from .models import MetadataOption, StepVersion

MAX_TOKENS = {
    "site_crawl": 4000,
    "research": 6000,
    "outline": 8000,
    "draft": 16000,
    "review_edit": 16000,
    "localise": 16000,
    "hero_image": 600,
}


class StepError(Exception):
    """A problem the user can fix; the message is shown on the run screen."""


@dataclass
class StepOutput:
    content: str
    provider: str = ""
    model: str = ""
    note: str = ""
    image: object = None
    stats: dict = field(default_factory=dict)
    extra_metrics: dict = field(default_factory=dict)


def _profile(step):
    return settings.AI_PROFILES.get(step.definition.profile or "", {})


def _target(step):
    """(provider, model, options) chosen for the step, falling back to its profile default."""
    profile = _profile(step)
    provider, model = step.provider or profile.get("provider"), step.model or profile.get("model")
    if not provider or not model:
        raise StepError("No model is chosen for this step. Pick one on the right and regenerate.")
    item = catalog.find(provider, model)
    options = (
        {**profile.get("options", {})}
        if (provider, model) == (profile.get("provider"), profile.get("model"))
        else {}
    )
    options.update((item.options or {}) if item else {})
    return provider, model, options


def _call_text(step, messages, max_tokens=None, use_profile=None):
    """Generate with the step's model; on failure use the profile's fallback model once."""
    if use_profile:
        profile = settings.AI_PROFILES.get(use_profile, {})
        provider, model, options = profile["provider"], profile["model"], dict(profile.get("options", {}))
    else:
        profile = _profile(step)
        provider, model, options = _target(step)
    options = {"temperature": 0.6, "max_tokens": max_tokens or MAX_TOKENS.get(step.key, 8000), **options}
    try:
        return generate(provider, model, messages, options)
    except ProviderError as error:
        fallback = profile.get("fallback")
        if not fallback or (fallback["provider"], fallback["model"]) == (provider, model):
            raise
        result = generate(
            fallback["provider"], fallback["model"], messages, {**options, **fallback.get("options", {})}
        )
        result.stats["fallback_from"] = f"{provider}/{model} ({error.kind})"
        return result


def _text_output(step, result, content=None, note=""):
    if result.stats.get("fallback_from"):
        note = f"Used the fallback model because {result.stats['fallback_from']} failed.\n\n{note}".strip()
    return StepOutput(
        content=content if content is not None else result.text.strip(),
        provider=result.provider,
        model=result.model,
        note=note,
        stats=result.stats,
    )


def _require(value, message):
    if not value or not value.strip():
        raise StepError(message)
    return value


# ---- Steps ----


def site_crawl(step):
    brief = step.run.brief
    _require(brief.site_domain, "Add the target site's URL to the brief, then retry.")
    pages = webfetch.crawl_site(
        brief.site_domain,
        max_pages=settings.STUDIO_CRAWL_MAX_PAGES,
        pace_seconds=settings.STUDIO_CRAWL_PACE_SECONDS,
    )
    read = [p for p in pages if p.method != "skipped"]
    if len(read) < 2:
        raise StepError(
            "Couldn't read enough public pages on the target site (it may block automated "
            "reading or need a login). Add article URLs to the brief notes and retry."
        )
    stats, rows = [], []
    for page in pages:
        if page.method == "skipped":
            rows.append(f"| {page.url} | Skipped | – | – | {page.reason} |")
            continue
        words = len(page.text.split())
        grade = round(textstat.flesch_kincaid_grade(page.text), 1) if words > 100 else None
        first_person = len(re.findall(r"\b(I|I'm|I've|my|me)\b", page.text))
        rows.append(
            f"| {page.url} | {'Direct' if page.method == 'direct' else 'Reader service'} | {words} | "
            f"{grade if grade is not None else '–'} | |"
        )
        excerpt = " ".join(page.text.split()[:150])
        stats.append(
            f"### {page.url}\nWords: {words} · FKGL: {grade} · first-person words: {first_person}\n"
            f"Headings: {'; '.join(page.headings[:8]) or 'none found'}\nExcerpt: {excerpt}\n"
        )
    messages = prompting.render("site_profile", prompting.context_for(step, {"page_stats": "\n".join(stats)}))
    result = _call_text(step, messages)
    pages_table = "\n".join(
        [
            "## Pages read",
            "",
            "| Page | How it was read | Words | FKGL | Note |",
            "|---|---|---|---|---|",
            *rows,
        ]
    )
    return _text_output(step, result, content=f"{result.text.strip()}\n\n{pages_table}\n")


def research(step):
    return _text_output(step, _call_text(step, prompting.render("research", prompting.context_for(step))))


def outline(step):
    return _text_output(step, _call_text(step, prompting.render("outline", prompting.context_for(step))))


def draft(step):
    context = prompting.context_for(step)
    _require(context["outline"], "Approve the outline before drafting.")
    result = _call_text(step, prompting.render("draft", context))
    article, options = textclean.split_metadata(result.text)
    run = step.run
    # New suggestions replace earlier unselected AI ones; your own options and selections stay.
    run.metadata_options.filter(source=StepVersion.Source.AI, selected=False).delete()
    has_selected = set(run.metadata_options.filter(selected=True).values_list("kind", flat=True))
    for kind, items in options.items():
        for index, text in enumerate(items):
            MetadataOption.objects.create(
                run=run, kind=kind, text=text[:300], selected=index == 0 and kind not in has_selected
            )
    note = (
        ""
        if options
        else "The model didn't return title and meta options; add your own on the Title and meta screen."
    )
    return _text_output(step, result, content=article, note=note)


def review_edit(step):
    source = prompting.approved_output(step.run, "draft")
    _require(source, "Approve the draft before review and edit.")
    brief = step.run.brief
    used = []

    def call(prompt_name, context):
        messages = prompting.render(prompt_name, {**prompting.context_for(step), **context})
        result = _call_text(step, messages, max_tokens=4000 if prompt_name == "review_splits" else 16000)
        used.append(result)
        return result.text

    outcome = review.run_sequence(
        source,
        {"fkgl": float(brief.fkgl), "region": brief.get_region_display(), "pkeyword": brief.pkeyword},
        call,
    )
    last = used[-1] if used else None
    fallbacks = [r.stats["fallback_from"] for r in used if r.stats.get("fallback_from")]
    lines = [f"{s['number']}. **{s['name']}**: {s['summary']}" for s in outcome.substeps]
    note = "## Review sequence\n\n" + "\n".join(lines)
    if fallbacks:
        note = f"Used the fallback model for some sub-steps because {fallbacks[0]} failed.\n\n{note}"
    return StepOutput(
        content=outcome.text,
        provider=last.provider if last else "",
        model=last.model if last else "",
        note=note,
        extra_metrics={
            "review": {"substeps": outcome.substeps, "grades": outcome.grades, "proposals": outcome.proposals}
        },
    )


def cleanup(step):
    run = step.run
    source = prompting.approved_output(run, "review_edit") or prompting.approved_output(run, "draft")
    _require(source, "There is no approved article to clean up yet.")
    try:
        cleaned, stats = quality_scripts.clean_text(source)
        note = "Cleaned with the clean-user-facing-text script."
        if stats:
            note += f" Stats: {stats}"
    except (quality_scripts.ScriptError, OSError):
        cleaned, report = textclean.clean(source)
        note = (
            f"Removed {report['invisible_removed']} hidden characters and normalised "
            f"{report['spaces_normalised']} unusual spaces (built-in cleaner)."
        )
    return StepOutput(content=cleaned, note=note)


def hero_image(step):
    from wagtail.images import get_image_model

    run, brief = step.run, step.run.brief
    article = prompting.approved_output(run, "cleanup") or prompting.approved_output(run, "draft")
    title_option = run.metadata_options.filter(kind="title", selected=True).first()
    title = title_option.text if title_option else brief.topic
    context = prompting.context_for(
        step, {"title": title, "excerpt": " ".join((article or brief.topic).split()[:150])}
    )
    prompt_result = _call_text(step, prompting.render("hero_prompt", context), use_profile="fast")
    image_prompt = " ".join(prompt_result.text.split())[:1500]

    provider, model, options = _target(step)
    profile = _profile(step)
    try:
        image = generate_image(provider, model, image_prompt, options)
    except ProviderError as error:
        fallback = profile.get("fallback")
        if not fallback:
            raise
        image = generate_image(
            fallback["provider"], fallback["model"], image_prompt, fallback.get("options", {})
        )
        image.stats["fallback_from"] = f"{provider}/{model} ({error.kind})"
    ext = image.mime_type.split("/")[-1].replace("jpeg", "jpg")
    stored = get_image_model().objects.create(
        title=f"Hero: {title}"[:255],
        file=ImageFile(io.BytesIO(image.data), name=f"hero-run{run.pk}.{ext}"),
    )
    note = f"Image prompt:\n\n{image_prompt}"
    if image.stats.get("fallback_from"):
        note = f"Used the fallback image model because {image.stats['fallback_from']} failed.\n\n{note}"
    return StepOutput(
        content=f"Hero image for “{title}”.",
        provider=image.provider,
        model=image.model,
        note=note,
        image=stored,
    )


def localise(step):
    brief = step.run.brief
    _require(brief.localise_to, "Choose “Localise to” in the brief, then retry.")
    context = prompting.context_for(step)
    _require(context["draft"], "There is no approved article to localise yet.")
    result = _call_text(step, prompting.render("localise", context))
    article, _, notes = result.text.partition("## Localisation notes")
    return _text_output(
        step,
        result,
        content=article.strip(),
        note=f"## Localisation notes\n{notes.strip()}" if notes.strip() else "",
    )


def publish(step):
    return StepOutput(
        content="Everything before this step is approved. Approve to finish the run.\n\n"
        "Creating the Wagtail page and exports arrive in milestone M7."
    )


EXECUTORS = {
    "site_crawl": site_crawl,
    "research": research,
    "outline": outline,
    "draft": draft,
    "review_edit": review_edit,
    "cleanup": cleanup,
    "hero_image": hero_image,
    "localise": localise,
    "publish": publish,
}

FRIENDLY_ERRORS = {
    "not_free": "This model isn't included in the free plan. Choose another model and regenerate.",
    "rate_limited": "The free limit for this model was reached. Try again later or choose another model.",
    "network": "Couldn't reach the provider. If it's Ollama on your PC, check that it's running.",
    "not_configured": "This provider isn't set up. Add its key to .env, or choose another model.",
    "auth": "The provider rejected the API key. Check the key in .env.",
    "server": "The provider had a temporary error. Retry in a few minutes.",
    "unavailable": "This model isn't available to your account. Choose another model.",
}


def friendly_error(error):
    if isinstance(error, ProviderError):
        return f"{FRIENDLY_ERRORS.get(error.kind, 'The model call failed.')} (Details: {str(error)[:300]})"
    return str(error)
