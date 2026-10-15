"""The standalone Image generator: one image at a time, not tied to a brief or a run.

It reuses the hero step's pieces (apps/studio/executors.py, apps/quality/hero.py): the photo prompt and the
vision check from the same templates, the sds-hero-stock scripts for a branded blog hero, `hero.for_host`
for an unbranded lead image at a given size, and the skill's inner_logo.py for an in-article image. The
worker runs `execute` (tasks.run_image_job); tests call it directly.
"""

import io
import json
import logging
import re
import subprocess
from types import SimpleNamespace
from urllib.parse import urlparse

import httpx
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.images import ImageFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone
from django.utils.text import slugify

from apps.ai.redact import redact
from apps.ai.service import generate_image
from apps.ai.types import ProviderError
from apps.quality import hero, infographic

from . import executors, prompting
from .models import ImageJob
from .pipeline import profile_for

logger = logging.getLogger(__name__)

DEFAULT_SIZES = {ImageJob.Kind.LEAD: hero.DEFAULT_HOST_SIZE, ImageJob.Kind.INLINE: (1200, 675)}
MAX_SIDE = 4000

# The composition the photo prompt and the vision check ask for, per kind. A blog hero and a lead image use
# the content types' own wording (types.yaml), so the generator and the pipeline never drift apart.
INLINE = {
    "hero_composition": (
        "The photo illustrates a point inside an article. A small SDS Manager logo goes in one corner "
        "afterwards, so keep the corners calm. Compose a normal editorial photograph with the subject "
        "clearly in frame."
    ),
    "hero_framing": (
        "- wide frame; the subject and their task well inside the frame, clear of the edges, not looking "
        "at the camera\n"
        "- show the process, equipment or setting the text explains, factually"
    ),
    "hero_layout": "It sits inside an article with a small logo in one corner.",
}


class ImageJobError(Exception):
    """A problem the user can fix; the message is shown on the job's page."""


def size_for(job):
    if job.kind == ImageJob.Kind.HERO:
        return None
    default = DEFAULT_SIZES[job.kind]
    return (job.width or default[0], job.height or default[1])


def _composition(job):
    if job.kind == ImageJob.Kind.INLINE:
        return dict(INLINE)
    content_type = "seo_blog" if job.kind == ImageJob.Kind.HERO else "outbound"
    structure = prompting.type_structure(content_type)
    return {key: structure[key] for key in ("hero_composition", "hero_framing", "hero_layout")}


def _context(job):
    title = job.headline or job.description or "Workplace chemical safety"
    return {
        "title": title,
        "topic": job.description or title,
        "region": job.get_region_display(),
        "excerpt": job.description or title,
        "regenerate_block": "",
        **_composition(job),
    }


def _photo_prompt(job, context):
    if job.photo_prompt.strip():
        return executors.with_no_text(job.photo_prompt[:1500])
    if not (job.description or job.headline).strip():
        raise ImageJobError("Describe what the image shows, write a photo prompt, or upload a photo.")
    caller = SimpleNamespace(key="hero_image")  # _call_text only reads .key when a task is given
    result = executors._call_text(caller, prompting.render("hero_prompt", context), task="hero_prompt")
    prompt = " ".join(result.text.split())[:1500]
    if not prompt:
        raise ImageJobError("The model returned an empty photo prompt. Try again or write one yourself.")
    return executors.with_no_text(prompt)


def _generate(prompt):
    """(ImageResult, note): the image profile's model (Settings › Default models › Hero image), then its
    fallback."""
    profile = profile_for("hero_image")
    try:
        return generate_image(profile["provider"], profile["model"], prompt, profile.get("options", {})), ""
    except ProviderError as error:
        fallback = profile.get("fallback")
        if not fallback:
            raise
        image = generate_image(fallback["provider"], fallback["model"], prompt, fallback.get("options", {}))
        return image, f"Used the fallback image model because {profile['model']} failed ({error.kind})."


def _save_image(title, data, name, description=""):
    from wagtail.images import get_image_model

    return get_image_model().objects.create(
        title=title[:255], description=description, file=ImageFile(io.BytesIO(data), name=name)
    )


def _read(image):
    with image.file.open("rb") as handle:
        return handle.read()


def _finish(job, data, vision, context, markup):
    """The finished HeroResult for the job's kind, from photo bytes and the vision check."""
    if job.kind == ImageJob.Kind.HERO:
        try:
            return hero.brand(data, markup, vision)
        except (hero.BrandingError, OSError, subprocess.SubprocessError) as error:
            return hero.HeroResult(metrics={"headline": markup}, flags=[f"Branding failed: {error}"])
    result = hero.for_host(data, size_for(job), vision)
    if job.kind == ImageJob.Kind.INLINE:
        try:
            branded, report = hero.brand_inner(result.png, "image.png", job.corner)
        except (hero.BrandingError, OSError, subprocess.SubprocessError) as error:
            result.flags.append(f"Branding failed: {error}")
        else:
            result.png = branded
            result.metrics["logo"] = report
    return result


def run(job):
    """Make the job's image. Returns the metrics; raises ImageJobError or ProviderError."""
    if job.kind == ImageJob.Kind.INFOGRAPHIC:
        return _run_infographic(job)
    context = _context(job)
    markup = hero.headline_markup(job.headline or job.description, job.region) if job.kind == "hero" else ""
    if job.kind == ImageJob.Kind.HERO and not markup.strip():
        raise ImageJobError("A blog hero needs a headline (the article's H1).")
    flags, notes, image_prompt = [], [], ""
    step = SimpleNamespace(key="hero_image")
    generated = job.source is None
    if generated:
        image_prompt = _photo_prompt(job, context)
    for attempt in (1, 2):
        if generated:
            image, note = _generate(image_prompt)
            notes += [note] if note else []
            job.provider, job.model = image.provider, image.model
            ext = image.mime_type.split("/")[-1].replace("jpeg", "jpg")
            photo = _save_image(
                f"Image generator photo: {context['title']}", image.data, f"imagegen-photo-{job.pk}.{ext}"
            )
            data = image.data
        else:
            photo, data = job.source, _read(job.source)
        if job.kind == ImageJob.Kind.HERO:
            # Exactly 16:9 before the vision check, so its subject box matches the photo that is branded.
            data = hero.to_16_9(data)
        vision, vision_problem = executors._look_at_photo(step, data, context)
        result = _finish(job, data, vision, context, markup)
        if not generated or attempt == 2 or not result.subject_too_far_left:
            break
        flags.append(
            f"The first photo had the subject at {vision['subject'][0]:.0%} of the width, too far left "
            "for the layout, so a second photo was generated."
        )
        photo.delete()
        image_prompt += " " + executors.PLACE_RIGHT

    flags += executors._vision_flags(vision, vision_problem, result)
    flags += result.flags
    alt_text = (vision or {}).get("alt_text", "")
    stem = hero.file_stem(markup) if markup else slugify(job.headline or job.description)[:80] or "image"
    files = {}
    final = None
    if result.ready:
        final = _save_image(
            f"{job.get_kind_display().split(' (')[0]}: {context['title']}",
            result.png,
            f"{stem}.png",
            alt_text,
        )
        for kind, data in (("webp", result.webp), ("svg", result.svg)):
            if data:
                files[kind] = default_storage.save(
                    f"studio/images/job-{job.pk}/{stem}.{kind}", ContentFile(data)
                )
    job.photo, job.image = photo, final
    return {
        **result.metrics,
        "headline": markup,
        "branded": result.branded,
        "headline_problem": result.headline_problem,
        "size": list(size_for(job)) if size_for(job) else [1440, 810],
        "flags": flags,
        "notes": notes,
        "vision": vision,
        "alt_text": alt_text,
        "image_prompt": image_prompt,
        "files": files,
        "file_stem": stem,
        "needs_a_look": executors.hero_needs_a_look(flags, final is not None),
    }


def _json_object(text):
    match = re.search(r"\{.*\}", text or "", re.S)
    try:
        data = json.loads(match.group(0)) if match else None
    except json.JSONDecodeError:
        data = None
    return data if isinstance(data, dict) else None


def write_spec(template, description):
    """The template's spec, filled by the model from a description (the only source it may use)."""
    caller = SimpleNamespace(key="hero_image")
    context = {
        "template": f"{template} ({infographic.LABELS[template]})",
        "guide": infographic.spec_guide([template]),
        "description": description,
    }
    result = executors._call_text(
        caller, prompting.render("infographic_spec", context), max_tokens=4000, task="hero_prompt"
    )
    spec = _json_object(result.text)
    if spec is None:
        raise ImageJobError("The model didn't return a usable infographic spec. Try again or paste one.")
    return spec


def _run_infographic(job):
    """Draw an infographic from its template and spec (written from the description when there is none),
    with the template's checks; a blocked one gets no image, only the problems to fix."""
    if job.template not in infographic.TEMPLATES:
        raise ImageJobError("Choose an infographic template.")
    spec_source = "given"
    if not job.spec:
        if not job.description.strip():
            raise ImageJobError(
                "Describe what the infographic shows (its facts and figures), or paste a spec."
            )
        job.spec = write_spec(job.template, job.description)
        spec_source = "written from the description"
    # Figures must come from the article (a planned infographic) or from the description it was written from.
    if job.plan_id and job.plan.article_text:
        article, source_name = job.plan.article_text, "the article"
    elif spec_source != "given":
        article, source_name = job.description, "your description"
    else:
        article, source_name = None, "the article"
    try:
        result = infographic.render(job.template, job.spec, article=article, source_name=source_name)
    except infographic.InfographicError as error:
        raise ImageJobError(str(error)) from error
    title = str(job.spec.get("title") or job.description or "infographic").replace("**", "")
    stem = slugify(title)[:80] or "infographic"
    files, final = {}, None
    if not result.blocked:
        final = _save_image(f"Infographic: {title}", result.png, f"{stem}.png", result.alt)
        for kind, data in (("webp", result.webp), ("svg", result.svg.encode())):
            files[kind] = default_storage.save(f"studio/images/job-{job.pk}/{stem}.{kind}", ContentFile(data))
    job.photo, job.image = None, final
    return {
        "template": job.template,
        "spec_source": spec_source,
        "problems": result.problems,
        "flags": [p["text"] for p in result.problems],
        "blocked": result.blocked,
        "alt_text": result.alt,
        "files": files,
        "file_stem": stem,
        "size": [infographic.WEBP_WIDTH, round(result.height * infographic.WEBP_WIDTH / infographic.W)],
        "headline": "",
        "needs_a_look": result.blocked,
    }


def enqueue(job):
    from django.conf import settings

    if not getattr(settings, "STUDIO_EXECUTE_STEPS", False):
        return
    from .tasks import run_image_job

    job_id = job.pk
    transaction.on_commit(lambda: run_image_job.enqueue(job_id))


def execute(job_id):
    """Run one queued job. Safe to call twice: only a QUEUED job is picked up."""
    with transaction.atomic():
        job = ImageJob.objects.select_for_update().get(pk=job_id)
        if job.status != ImageJob.Status.QUEUED:
            return
        job.status, job.started_at, job.error = ImageJob.Status.RUNNING, timezone.now(), ""
        job.save(update_fields=["status", "started_at", "error"])
    try:
        job.metrics = run(job)
        job.status = ImageJob.Status.DONE
    except (ProviderError, executors.StepError, ImageJobError) as error:
        message = executors.friendly_error(error) if isinstance(error, ProviderError) else str(error)
        job.status, job.error = ImageJob.Status.FAILED, redact(message)
    except Exception as error:  # noqa: BLE001 - never leave a job stuck in "running"
        logger.exception("Image job %s crashed", job.pk)
        job.status, job.error = ImageJob.Status.FAILED, redact(f"Unexpected error: {error!r}"[:1000])
    job.finished_at = timezone.now()
    job.save()


def again(job, user, **changes):
    """A new job from this one's inputs; with `same_photo`, its photo is reused (a new headline or size)."""
    same_photo = changes.pop("same_photo", False)
    fields = (
        "kind",
        "description",
        "headline",
        "photo_prompt",
        "region",
        "width",
        "height",
        "corner",
        "template",
    )
    values = {name: getattr(job, name) for name in fields}
    values["spec"] = {} if changes.pop("rewrite", False) else changes.pop("spec", None) or job.spec
    values["plan"], values["section"] = job.plan, job.section
    values.update({key: value for key, value in changes.items() if value not in (None, "")})
    source = (job.photo or job.source) if same_photo else None  # a new photo is generated otherwise
    new = ImageJob.objects.create(**values, source=source, created_by=user)
    enqueue(new)
    return new


def file_bytes(job, kind):
    """The job's PNG (the finished image), WebP or layered SVG, or None."""
    if kind == "png":
        return _read(job.image) if job.image else None
    if kind == "webp" and job.image and not job.metrics.get("files", {}).get("webp"):
        # Lead and in-article images: the finished PNG as WebP at its own size.
        from PIL import Image

        with Image.open(io.BytesIO(_read(job.image))) as picture:
            out = io.BytesIO()
            picture.convert("RGB").save(out, "WEBP", quality=88)
        return out.getvalue()
    name = (job.metrics.get("files") or {}).get(kind)
    if not name or not default_storage.exists(name):
        return None
    with default_storage.open(name, "rb") as handle:
        return handle.read()


def validate_size(width, height):
    for value in (width, height):
        if value is not None and not 200 <= value <= MAX_SIDE:
            raise ImageJobError(f"Width and height must be between 200 and {MAX_SIDE} pixels.")


# ---- Images tailored to an existing article ----

ARTICLE_WORDS = 5000  # enough for any blog in the index; the planner reads structure, not every word
MAX_INLINE = 4  # photos
MAX_VISUALS = 5  # photos and infographics besides the hero
VISUAL_CUE = re.compile(r"\[VISUAL:\s*([^\]]+)\]")
SDSMANAGER_HOSTS = ("sdsmanager.com", "www.sdsmanager.com")


def sdsmanager_url(url):
    """The URL if it is an https page on sdsmanager.com (the planner never fetches other hosts)."""
    parsed = urlparse((url or "").strip())
    if parsed.scheme != "https" or parsed.hostname not in SDSMANAGER_HOSTS:
        raise ImageJobError(
            "Only published sdsmanager.com articles can be read; paste other articles instead."
        )
    return parsed.geturl()


def article_choices(limit=30):
    """Grouped choices: studio runs with an approved article, then the published sdsmanager.com articles in
    the internal index."""
    from . import houseref
    from .models import GenerationRun, StepRun

    runs = (
        GenerationRun.objects.filter(
            steps__key__in=("cleanup", "review_edit", "draft"), steps__status=StepRun.Status.APPROVED
        )
        .select_related("brief")
        .distinct()
        .order_by("-pk")[:limit]
    )
    studio = [(f"run:{run.pk}", f"Run {run.pk}: {run.brief.topic}") for run in runs]
    published = [
        (f"url:{row['url']}", f"{row['keyword']} ({row['region']})") for row in houseref._index_rows()
    ]
    groups = []
    if studio:
        groups.append(("Studio runs", studio))
    if published:
        groups.append(("Published on sdsmanager.com", published))
    return groups


def _page_markdown(html):
    """Headings and paragraphs of a fetched article page as Markdown (the H1, H2s and H3s kept)."""
    from .webfetch import _TextExtractor

    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S | re.I)
    title = " ".join(re.sub(r"<[^>]+>", " ", h1.group(1)).split()) if h1 else ""
    extractor = _TextExtractor()
    extractor.feed(html)
    headings = set(extractor.headings)
    lines = []
    for line in extractor.text.splitlines():
        line = " ".join(line.split())
        if not line or line == title:
            continue
        lines.append(f"## {line}" if line in headings else line)
    return (f"# {title}\n\n" if title else "") + "\n\n".join(lines)


def fetch_article(url):
    from . import webfetch

    url = sdsmanager_url(url)
    with webfetch._client() as client:
        robots = webfetch.robots_for(url, client)
        if not robots.can_fetch(settings.AI_USER_AGENT, url):
            raise ImageJobError(
                "sdsmanager.com's robots.txt doesn't allow reading that page; paste it instead."
            )
        try:
            response = client.get(url)
        except httpx.HTTPError as error:
            raise ImageJobError(
                f"Couldn't read the page ({error.__class__.__name__}); paste it instead."
            ) from error
    if response.status_code != 200 or "html" not in response.headers.get("content-type", ""):
        raise ImageJobError(
            f"The page answered HTTP {response.status_code}; check the URL or paste the article."
        )
    text = _page_markdown(response.text)
    if len(text.split()) < 150:
        raise ImageJobError("The page had too little text to read; paste the article instead.")
    return text


def load_article(plan):
    """The article as Markdown: the run's approved text, the fetched page, or what was pasted."""
    if plan.run_id:
        from apps.content import exports

        try:
            return exports.article_content(plan.run).text
        except exports.ArticleError as error:
            raise ImageJobError(str(error)) from error
    if plan.url:
        return fetch_article(plan.url)
    if plan.article_text.strip():
        return plan.article_text
    raise ImageJobError("There is no article to read.")


def run_visual_cues(run):
    """[(section, cue)] the review-and-edit step took out of the article (verify.finalise)."""
    step = run.steps.filter(key="review_edit").first()
    version = step.latest_version if step else None
    cues = ((version.metrics or {}).get("verification") or {}).get("visual_cues") if version else None
    return [(section, cue) for section, cue in cues or []]


def outline_of(text):
    """(H1, [H2...], [(section, cue)...]) from the article's Markdown."""
    h1 = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    sections, cues, current = [], [], "(intro)"
    for line in text.splitlines():
        heading = re.match(r"^##\s+(.+?)\s*$", line)
        if heading:
            current = heading.group(1).strip("* ")
            sections.append(current)
        for cue in VISUAL_CUE.findall(line):
            cues.append((current, " ".join(cue.split())))
    return (h1.group(1).strip("* ") if h1 else ""), sections, cues


def _plan_ideas(raw, h1, sections, article=""):
    """The planner's JSON, checked: one hero with the article's H1, in-article ideas on real sections, and
    each infographic drawn once (without the PNG) so the plan shows whether it passes its checks."""
    match = re.search(r"\{.*\}", raw, re.S)
    try:
        data = json.loads(match.group(0)) if match else {}
    except json.JSONDecodeError:
        data = {}
    if not isinstance(data, dict) or not isinstance(data.get("ideas"), list):
        raise ImageJobError("The model didn't return usable image ideas. Try again.")
    known = {s.lower(): s for s in sections}
    ideas, hero_seen = [], False
    for item in data["ideas"]:
        if not isinstance(item, dict) or not str(item.get("description") or "").strip():
            continue
        kind = item.get("kind") if item.get("kind") in ("hero", "infographic") else "inline"
        if kind == "hero":
            if hero_seen:
                continue
            hero_seen = True
            section = "Hero"
        else:
            section = known.get(str(item.get("section") or "").strip().lower())
            visuals = sum(i["kind"] != "hero" for i in ideas)
            photos = sum(i["kind"] == "inline" for i in ideas)
            if section is None or visuals >= MAX_VISUALS or (kind == "inline" and photos >= MAX_INLINE):
                continue
        if kind == "infographic":
            template, spec = item.get("template"), item.get("spec")
            if template not in infographic.TEMPLATES or not isinstance(spec, dict):
                continue
            try:
                check = infographic.render(template, spec, article=article, raster=False)
            except infographic.InfographicError:
                continue
            ideas.append(
                {
                    "kind": kind,
                    "section": section,
                    "headline": "",
                    "description": " ".join(str(item["description"]).split())[:600],
                    "why": " ".join(str(item.get("why") or "").split())[:300],
                    "template": template,
                    "template_label": infographic.LABELS[template],
                    "spec": spec,
                    "checks": [p["text"] for p in check.problems],
                    "passes": not check.blocked,
                }
            )
            continue
        ideas.append(
            {
                "kind": kind,
                "section": section,
                "headline": h1 if kind == "hero" else "",
                "description": " ".join(str(item["description"]).split())[:600],
                "why": " ".join(str(item.get("why") or "").split())[:300],
            }
        )
    ideas.sort(key=lambda idea: idea["kind"] != "hero")
    skipped = [
        " ".join(str(item).split())[:300] for item in (data.get("not_photos") or []) if str(item).strip()
    ]
    return ideas, skipped


def plan(plan_obj):
    """Read the article and ask the model for tailored image ideas. Returns (title, ideas, notes)."""
    text = load_article(plan_obj)
    h1, sections, cues = outline_of(text)
    if plan_obj.run_id and not cues:
        # [VISUAL:] cues leave the article at review and edit (no markers past review); they are kept there.
        cues = run_visual_cues(plan_obj.run)
    words = text.split()
    context = {
        "region": plan_obj.get_region_display(),
        "title": h1 or "(no H1 found)",
        "sections": "\n".join(f"- {s}" for s in sections) or "(no H2 headings found)",
        "cues": "\n".join(f"- under “{s}”: {c}" for s, c in cues) or "(none)",
        "article": " ".join(words[:ARTICLE_WORDS]) if len(words) > ARTICLE_WORDS else text,
        "max_inline": MAX_INLINE,
        "max_visuals": MAX_VISUALS,
        "templates": infographic.spec_guide(),
    }
    caller = SimpleNamespace(key="hero_image")
    result = executors._call_text(
        caller, prompting.render("image_plan", context), max_tokens=8000, task="hero_prompt"
    )
    ideas, skipped = _plan_ideas(result.text, h1, sections, text)
    if not ideas:
        raise ImageJobError("The model proposed no usable images for this article. Try again.")
    if h1 and not any(idea["kind"] == "hero" for idea in ideas):
        ideas.insert(0, {"kind": "hero", "section": "Hero", "headline": h1, "description": h1, "why": ""})
    notes = "\n".join(f"Not a photo: {item}" for item in skipped)
    return h1, ideas, notes, text


def enqueue_plan(plan_obj):
    from django.conf import settings as django_settings

    if not getattr(django_settings, "STUDIO_EXECUTE_STEPS", False):
        return
    from .tasks import run_image_plan

    plan_id = plan_obj.pk
    transaction.on_commit(lambda: run_image_plan.enqueue(plan_id))


def execute_plan(plan_id):
    from .models import ImagePlan

    with transaction.atomic():
        plan_obj = ImagePlan.objects.select_for_update().get(pk=plan_id)
        if plan_obj.status != ImagePlan.Status.QUEUED:
            return
        plan_obj.status, plan_obj.error = ImagePlan.Status.RUNNING, ""
        plan_obj.save(update_fields=["status", "error"])
    try:
        title, ideas, notes, text = plan(plan_obj)
        plan_obj.title = plan_obj.title or title or plan_obj.source_label
        plan_obj.article_text = text  # what infographic figures are checked against when they are made
        plan_obj.ideas, plan_obj.notes, plan_obj.status = ideas, notes, ImagePlan.Status.READY
    except (ProviderError, executors.StepError, ImageJobError) as error:
        message = executors.friendly_error(error) if isinstance(error, ProviderError) else str(error)
        plan_obj.status, plan_obj.error = ImagePlan.Status.FAILED, redact(message)
    except Exception as error:  # noqa: BLE001 - never leave a plan stuck in "running"
        logger.exception("Image plan %s crashed", plan_obj.pk)
        plan_obj.status, plan_obj.error = (
            ImagePlan.Status.FAILED,
            redact(f"Unexpected error: {error!r}"[:1000]),
        )
    plan_obj.finished_at = timezone.now()
    plan_obj.save()


def make_from_plan(plan_obj, chosen, user):
    """One ImageJob per chosen idea ({kind, section, headline, description, template, spec}), queued."""
    jobs = []
    for idea in chosen:
        job = ImageJob.objects.create(
            kind=idea["kind"],
            headline=idea.get("headline", "") if idea["kind"] == "hero" else "",
            description=idea["description"],
            region=plan_obj.region,
            plan=plan_obj,
            section=idea.get("section", ""),
            template=idea.get("template", "") if idea["kind"] == "infographic" else "",
            spec=idea.get("spec") or {} if idea["kind"] == "infographic" else {},
            created_by=user,
        )
        enqueue(job)
        jobs.append(job)
    return jobs
