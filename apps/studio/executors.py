"""What each pipeline step does when the worker runs it. Each executor returns a StepOutput."""

import base64
import io
import json
import re
import subprocess
from dataclasses import dataclass, field

import textstat
from django.conf import settings
from django.core.files.images import ImageFile

from apps.ai import catalog
from apps.ai.service import generate, generate_image
from apps.ai.types import ProviderError
from apps.quality import hero, review
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
    "hero_image": 3000,  # a 90-word prompt, but reasoning models (gpt-oss) think first
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


VISION_KEYS = ("subject", "person_at_left_edge", "facing", "readable_text", "safety_issues", "scene")


def _parse_vision(text):
    """The vision model's JSON, validated; None if it isn't usable."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        data = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        return None
    vision = {key: data.get(key) for key in VISION_KEYS}
    box = vision["subject"]
    valid_box = (
        isinstance(box, list)
        and len(box) == 4
        and all(isinstance(v, int | float) and 0 <= v <= 1 for v in box)
        and box[0] < box[2]
        and box[1] < box[3]
    )
    vision["subject"] = [float(v) for v in box] if valid_box else None
    for key in ("readable_text", "safety_issues"):
        vision[key] = [str(item) for item in vision[key]] if isinstance(vision[key], list) else []
    vision["person_at_left_edge"] = vision["person_at_left_edge"] is not False
    return vision


def _vision_image(data, max_width=1024):
    from PIL import Image

    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        if image.width > max_width:
            image = image.resize((max_width, round(image.height * max_width / image.width)))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=88)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode()


def _look_at_photo(step, data, context):
    """Skill step 2: subject box, facing, readable text and safety problems. Returns (vision, problem)."""
    messages = prompting.render("hero_vision", context)
    messages[-1]["content"] = [
        {"type": "text", "text": messages[-1]["content"]},
        {"type": "image_url", "image_url": {"url": _vision_image(data)}},
    ]
    try:
        result = _call_text(step, messages, max_tokens=2000, use_profile="vision")
    except ProviderError as error:
        return None, f"The vision check failed ({error.kind}): {str(error)[:200]}"
    vision = _parse_vision(result.text)
    if vision is None:
        return None, "The vision model didn't return usable JSON."
    vision["model"] = f"{result.provider}/{result.model}"
    vision["fallback_from"] = result.stats.get("fallback_from", "")
    return vision, ""


def _generate_photo(step, image_prompt):
    provider, model, options = _target(step)
    profile = _profile(step)
    try:
        return generate_image(provider, model, image_prompt, options)
    except ProviderError as error:
        # A model chosen for this run (e.g. ComfyUI) falls back to the profile's default first:
        # the profile's own fallback (FLUX.1 schnell) only makes square images.
        fallback = profile.get("fallback")
        if profile.get("model") and (provider, model) != (profile["provider"], profile["model"]):
            fallback = {k: profile[k] for k in ("provider", "model", "options") if k in profile}
        if not fallback:
            raise
        image = generate_image(
            fallback["provider"], fallback["model"], image_prompt, fallback.get("options", {})
        )
        image.stats["fallback_from"] = f"{provider}/{model} ({error.kind})"
        return image


PLACE_RIGHT = (
    "Composition: the person and everything they work with are entirely in the right 35% of the "
    "frame; the left 60% is empty, bright background."
)


def _new_photo(step, image_prompt, title):
    """Generate a photo and save it as a Wagtail image. (image, data, provider, model, note)."""
    from wagtail.images import get_image_model

    image = _generate_photo(step, image_prompt)
    note = ""
    if image.stats.get("fallback_from"):
        note = f"Used the fallback image model because {image.stats['fallback_from']} failed.\n\n"
    ext = image.mime_type.split("/")[-1].replace("jpeg", "jpg")
    photo = get_image_model().objects.create(
        title=f"Hero photo (unbranded): {title}"[:255],
        file=ImageFile(io.BytesIO(image.data), name=f"hero-photo-run{step.run_id}.{ext}"),
    )
    return photo, image.data, image.provider, image.model, note


def _previous_photo(step):
    """(Wagtail image, image prompt, provider, model) of the latest version's unbranded photo, or None."""
    from wagtail.images import get_image_model

    latest = step.latest_version
    hero_metrics = (latest.metrics or {}).get("hero", {}) if latest else {}
    photo = get_image_model().objects.filter(pk=hero_metrics.get("photo_image_id")).first()
    if photo is None:
        return None
    return photo, hero_metrics.get("image_prompt", ""), latest.provider, latest.model


def _hero_note(hero_metrics, image_prompt):
    lines = [f"Headline: `{hero_metrics['headline']}`"]
    vision = hero_metrics.get("vision")
    if vision:
        used = f"Vision check: {vision['model']}"
        if vision.get("fallback_from"):
            used += f" (fallback, because {vision['fallback_from']} failed)"
        lines.append(used)
    if hero_metrics["headline_problem"]:
        lines += [
            "",
            f"**The headline is too long for the hero.** {hero_metrics['headline_problem']}",
            "To fix it, regenerate with a note that starts with `Headline:` and a shorter version "
            "(the periwinkle part in `**`, ` | ` for the line break). The same photo is reused.",
        ]
    if hero_metrics["flags"]:
        lines += ["", "## Problems to check", "", *[f"- {flag}" for flag in hero_metrics["flags"]]]
    fit, contrast = hero_metrics.get("headline_fit"), hero_metrics.get("contrast")
    if fit:
        lines += [
            "",
            f"Headline fit: {fit['lines']} lines at {fit['size_px']} px ({fit['scale_percent']}% of the "
            f"template), ending at x={fit['ends_x']} of 720 (limit {fit['limit_x']}).",
        ]
    if contrast:
        lines.append(
            "Headline contrast: " + ", ".join(f"{name} {value}:1" for name, value in contrast.items())
        )
    lines += ["", "Image prompt:", "", image_prompt]
    return "\n".join(lines)


def hero_image(step):
    from wagtail.images import get_image_model

    Image = get_image_model()
    run, brief = step.run, step.run.brief
    article = prompting.approved_output(run, "cleanup") or prompting.approved_output(run, "draft")
    title_option = run.metadata_options.filter(kind="title", selected=True).first()
    title = title_option.text if title_option else brief.topic
    note = (step.regenerate_note or "").strip()
    headline_override = note[len("headline:") :].strip() if note.lower().startswith("headline:") else ""
    context = prompting.context_for(
        step, {"title": title, "excerpt": " ".join((article or brief.topic).split()[:150])}
    )
    markup = hero.headline_markup(headline_override or title, brief.region, brief.pkeyword)

    previous = _previous_photo(step) if headline_override else None
    fallback_note, flags = "", []
    if previous:
        # Only the headline changes: brand the same photo again.
        photo, image_prompt, provider, model = previous
        with photo.file.open("rb") as handle:
            data = handle.read()
    else:
        if headline_override:
            context["regenerate_block"] = ""
        prompt_result = _call_text(step, prompting.render("hero_prompt", context), use_profile="fast")
        image_prompt = " ".join(prompt_result.text.split())[:1500]
        _require(image_prompt, "The model returned an empty image prompt. Retry, or choose another model.")

    for attempt in (1, 2):
        if not previous:
            photo, data, provider, model, fallback_note = _new_photo(step, image_prompt, title)
        vision, vision_problem = _look_at_photo(step, data, context)
        try:
            result = hero.brand(data, markup, vision)
        except (hero.BrandingError, OSError, subprocess.SubprocessError) as error:
            result = hero.HeroResult(metrics={"headline": markup}, flags=[f"Branding failed: {error}"])
        if previous or attempt == 2 or not result.subject_too_far_left:
            break
        # Image models often centre the subject; one more try with a firmer placement.
        flags.append(
            f"The first photo had the subject at {vision['subject'][0]:.0%} of the width, too far left "
            "for the layout, so a second photo was generated."
        )
        photo.delete()
        image_prompt += " " + PLACE_RIGHT

    if vision_problem:
        flags.append(f"{vision_problem} Subject position, text and safety weren't checked; look yourself.")
    if vision:
        flags += [f"Safety: {issue}" for issue in vision["safety_issues"]]
        flags += [f"Readable text or logo in the photo: {item}" for item in vision["readable_text"]]
    flags += result.flags

    branded = None
    if result.branded:
        # The 1440x810 master, named after the visual copy (Wagtail would drop the skill's "@2x").
        branded = Image.objects.create(
            title=f"Hero: {title}"[:255],
            file=ImageFile(io.BytesIO(result.png), name=f"{hero.file_stem(markup)}.png"),
        )
    hero_metrics = {
        **result.metrics,
        "branded": result.branded,
        "headline_problem": result.headline_problem,
        "flags": flags,
        "vision": vision,
        "photo_image_id": photo.pk,
        "image_prompt": image_prompt,
    }
    state = "Branded hero" if branded else "Hero photo (not branded yet)"
    return StepOutput(
        content=f"{state} for “{title}”.",
        provider=provider,
        model=model,
        note=fallback_note + _hero_note(hero_metrics, image_prompt),
        image=branded or photo,
        extra_metrics={"hero": hero_metrics},
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
