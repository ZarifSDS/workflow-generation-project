"""The standalone Image generator: images not tied to a brief (apps/studio/imagegen.py)."""

import json
import re

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from wagtail.images import get_image_model
from wagtail.images import get_permission_policy as image_policy
from wagtail.images.forms import get_image_form
from wagtail.models import Collection

from .. import imagegen, permissions
from ..forms import ImageJobForm, ImagePlanForm
from ..models import GenerationRun, ImageJob, ImagePlan
from .common import StudioPage

RECENT = 20
DOWNLOADS = {
    "png": ("image/png", "png"),
    "webp": ("image/webp", "webp"),
    "svg": ("image/svg+xml", "svg"),
}


def _save_upload(upload, user):
    """The uploaded photo as a Wagtail image, through Wagtail's own form (type and size limits apply)."""
    if not image_policy().user_has_permission(user, "add"):
        raise PermissionDenied
    form = get_image_form(get_image_model())(
        {
            "title": f"Image generator upload: {upload.name}"[:255],
            "collection": Collection.get_first_root_node().pk,
        },
        {"file": upload},
        user=user,
    )
    if not form.is_valid():
        errors = [str(error) for field_errors in form.errors.values() for error in field_errors]
        raise ValueError(" ".join(errors) or "That file can't be used.")
    image = form.save(commit=False)
    image.uploaded_by_user = user
    image.save()
    return image


class ImageGeneratorView(StudioPage):
    """Two ways in: images tailored to an existing article (the model reads it and proposes a set), or one
    image from a description or an uploaded photo."""

    template_name = "studio/image_generator.html"
    page_title = "Image generator"
    header_icon = "image"
    post_permission = permissions.WRITING

    def get_breadcrumbs_items(self):
        return super().get_breadcrumbs_items() + [{"url": "", "label": "Image generator"}]

    def get_context_data(self, form=None, plan_form=None, tab=None, **kwargs):
        context = super().get_context_data(**kwargs)
        initial = self._initial()
        tab = tab or ("single" if initial or self.request.GET.get("tab") == "single" else "article")
        context.update(
            tab=tab,
            form=form or ImageJobForm(initial=initial),
            plan_form=plan_form or ImagePlanForm(),
            plans=ImagePlan.objects.prefetch_related("jobs__image")[:RECENT],
            jobs=ImageJob.objects.filter(plan__isnull=True).select_related("image")[:RECENT],
        )
        return context

    def _initial(self):
        """Prefill from an earlier job (?from=<id>), e.g. to try a variation."""
        source = self.request.GET.get("from", "")
        job = ImageJob.objects.filter(pk=source).first() if source.isdigit() else None
        if job is None:
            return {}
        fields = (
            "kind",
            "template",
            "headline",
            "description",
            "photo_prompt",
            "region",
            "width",
            "height",
            "corner",
        )
        initial = {name: getattr(job, name) for name in fields}
        if job.spec:
            initial["spec_json"] = json.dumps(job.spec, indent=2, ensure_ascii=False)
        return initial

    def post(self, request, *args, **kwargs):
        if request.POST.get("action") == "plan":
            return self._plan(request)
        form = ImageJobForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, "Some fields need attention.")
            return self.render_to_response(self.get_context_data(form=form, tab="single"))
        job = form.save(commit=False)
        if job.kind == ImageJob.Kind.INFOGRAPHIC:
            job.spec = form.cleaned_data.get("spec") or {}
        if upload := form.cleaned_data.get("upload"):
            try:
                job.source = _save_upload(upload, request.user)
            except ValueError as error:
                form.add_error("upload", str(error))
                return self.render_to_response(self.get_context_data(form=form, tab="single"))
        job.created_by = request.user
        job.save()
        imagegen.enqueue(job)
        messages.success(request, "Making the image. This page updates when it's ready (about a minute).")
        return redirect("studio:image_job", pk=job.pk)

    def _plan(self, request):
        form = ImagePlanForm(request.POST)
        if not form.is_valid():
            messages.error(request, "Choose the article first.")
            return self.render_to_response(self.get_context_data(plan_form=form, tab="article"))
        data = form.cleaned_data
        plan = ImagePlan(created_by=request.user)
        choice = data.get("article") or ""
        if choice.startswith("run:"):
            plan.run = get_object_or_404(GenerationRun.objects.select_related("brief"), pk=choice[4:])
            plan.region, plan.title = plan.run.brief.region, plan.run.brief.topic
        elif choice.startswith("url:") or data.get("url"):
            plan.url = data.get("url") or choice[4:]
            plan.region = _region_of(plan.url)
        else:
            plan.article_text = data["text"]
        plan.save()
        imagegen.enqueue_plan(plan)
        messages.success(request, "Reading the article and planning its images (under a minute).")
        return redirect("studio:image_plan", pk=plan.pk)


def _region_of(url):
    """sdsmanager.com/<region>/...: the region in the path, else US."""
    match = re.search(r"sdsmanager\.com/(us|uk|au|ca|nz)/", url)
    return match.group(1).upper() if match else "US"


class ImagePlanView(StudioPage):
    """The ideas for one article: edit, tick and make them; the images made so far below."""

    template_name = "studio/image_plan.html"
    header_icon = "image"
    post_permission = permissions.WRITING

    def dispatch(self, request, *args, **kwargs):
        self.plan = get_object_or_404(ImagePlan.objects.select_related("run__brief"), pk=kwargs["pk"])
        self.page_title = self.plan.title or "Images for an article"
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        return super().get_breadcrumbs_items() + [
            {"url": reverse("studio:images"), "label": "Image generator"},
            {"url": "", "label": self.page_title},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        jobs = list(self.plan.jobs.select_related("image").order_by("pk"))
        active, signature = _plan_state(self.plan)
        context.update(
            plan=self.plan,
            ideas=[_idea_view(idea) for idea in self.plan.ideas],
            jobs=jobs,
            active=active,
            signature=signature,
            made={job.section for job in jobs if job.status != ImageJob.Status.FAILED},
        )
        return context

    def post(self, request, *args, **kwargs):
        plan = self.plan
        if request.POST.get("action") == "replan":
            plan.status, plan.error, plan.ideas, plan.notes = ImagePlan.Status.QUEUED, "", [], ""
            plan.save()
            imagegen.enqueue_plan(plan)
            messages.success(request, "Planning again.")
            return redirect("studio:image_plan", pk=plan.pk)
        chosen = []
        for index, idea in enumerate(plan.ideas):
            if request.POST.get(f"pick-{index}") != "1":
                continue
            description = " ".join(request.POST.get(f"description-{index}", idea["description"]).split())
            headline = " ".join(request.POST.get(f"headline-{index}", idea.get("headline", "")).split())
            if not description or (idea["kind"] == "hero" and not headline):
                needs = "a description and a headline" if idea["kind"] == "hero" else "a description"
                messages.error(request, f"“{idea['section']}” needs {needs}.")
                return redirect("studio:image_plan", pk=plan.pk)
            spec = idea.get("spec")
            if idea["kind"] == "infographic" and request.POST.get(f"spec-{index}", "").strip():
                try:
                    spec = json.loads(request.POST[f"spec-{index}"])
                except json.JSONDecodeError as error:
                    messages.error(
                        request, f"The content of “{idea['section']}” isn't valid JSON ({error.msg})."
                    )
                    return redirect("studio:image_plan", pk=plan.pk)
            chosen.append(
                {**idea, "description": description[:600], "headline": headline[:200], "spec": spec}
            )
        if not chosen:
            messages.error(request, "Tick at least one image to make.")
            return redirect("studio:image_plan", pk=plan.pk)
        imagegen.make_from_plan(plan, chosen, request.user)
        messages.success(
            request,
            f"Making {len(chosen)} image{'s' if len(chosen) != 1 else ''}. They appear below as they finish.",
        )
        return redirect("studio:image_plan", pk=plan.pk)


def _idea_view(idea):
    """An idea for the plan page: an infographic's content as readable lines and as editable JSON."""
    if idea.get("kind") != "infographic":
        return idea
    spec = idea.get("spec") or {}
    lines = []
    for key in ("steps", "questions", "segments", "bars", "parts"):
        for item in spec.get(key) or []:
            if isinstance(item, dict):
                text = (
                    item.get("title") or item.get("question") or item.get("label") or item.get("name") or ""
                )
                value = item.get("value")
                lines.append(f"{text}: {value}" if value not in (None, "") else str(text))
    for column in spec.get("columns") or []:
        if isinstance(column, dict):
            lines.append(f"{column.get('title', '')}: {', '.join(map(str, column.get('items') or []))}")
    title = str(spec.get("title") or "").replace("**", "")
    return {
        **idea,
        "summary": ([title] if title else []) + lines[:10],
        "spec_json": json.dumps(spec, indent=2, ensure_ascii=False),
    }


def _plan_state(plan):
    """(active, signature): the page reloads when the signature changes."""
    jobs = list(plan.jobs.order_by("pk").values_list("pk", "status"))
    active = plan.is_open or any(status in ("queued", "running") for _, status in jobs)
    return active, f"{plan.status}:" + ",".join(f"{pk}={status}" for pk, status in jobs)


def image_plan_status(request, pk):
    if not request.user.has_perm(permissions.ACCESS):
        raise PermissionDenied
    active, signature = _plan_state(get_object_or_404(ImagePlan, pk=pk))
    return JsonResponse({"active": active, "signature": signature})


class ImageJobView(StudioPage):
    template_name = "studio/image_job.html"
    header_icon = "image"
    post_permission = permissions.WRITING

    def dispatch(self, request, *args, **kwargs):
        self.job = get_object_or_404(
            ImageJob.objects.select_related("image", "photo", "source"), pk=kwargs["pk"]
        )
        self.page_title = f"Image {self.job.pk}"
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        return super().get_breadcrumbs_items() + [
            {"url": reverse("studio:images"), "label": "Image generator"},
            {"url": "", "label": self.page_title},
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        job = self.job
        files = job.metrics.get("files") or {}
        downloads = []
        infographic_job = job.kind == ImageJob.Kind.INFOGRAPHIC
        if job.image:
            size = job.metrics.get("size") or [job.image.width, job.image.height]
            downloads = [("png", f"PNG ({job.image.width}×{job.image.height})")]
            if infographic_job:
                downloads += [("webp", f"WebP ({size[0]}×{size[1]}, for the CMS)"), ("svg", "SVG (editable)")]
            else:
                webp = "WebP (720×405, for the CMS)" if files.get("webp") else f"WebP ({size[0]}×{size[1]})"
                downloads.append(("webp", webp))
                if files.get("svg"):
                    downloads.append(("svg", "Layered SVG"))
        context.update(
            job=job,
            downloads=downloads,
            corners=ImageJob.Corner.choices,
            spec_json=json.dumps(job.spec, indent=2, ensure_ascii=False) if job.spec else "",
            template_label=job.get_template_display() if job.template else "",
        )
        return context

    def post(self, request, *args, **kwargs):
        """Another try: the same inputs and a new photo, or the same photo with a new headline, size or
        logo corner."""
        job = self.job
        action = request.POST.get("action")
        if job.kind == ImageJob.Kind.INFOGRAPHIC:
            return self._again_infographic(request, job, action)
        same_photo = action == "same_photo"
        if same_photo and not (job.photo or job.source):
            messages.error(request, "This job has no photo to reuse.")
            return redirect("studio:image_job", pk=job.pk)
        changes = {
            "headline": request.POST.get("headline", "").strip(),
            "corner": request.POST.get("corner", "").strip(),
        }
        try:
            width = int(request.POST["width"]) if request.POST.get("width") else None
            height = int(request.POST["height"]) if request.POST.get("height") else None
            imagegen.validate_size(width, height)
        except (ValueError, imagegen.ImageJobError) as error:
            messages.error(
                request, str(error) if isinstance(error, imagegen.ImageJobError) else "Use whole pixels."
            )
            return redirect("studio:image_job", pk=job.pk)
        changes.update(width=width, height=height)
        if changes["corner"] not in ImageJob.Corner.values:
            changes["corner"] = ""
        new = imagegen.again(job, request.user, same_photo=same_photo, **changes)
        messages.success(request, "Making the new version.")
        return redirect("studio:image_job", pk=new.pk)

    def _again_infographic(self, request, job, action):
        """Redraw with edited content, or have the model write the content again from the description."""
        if action == "rewrite":
            new = imagegen.again(job, request.user, rewrite=True)
        else:
            try:
                spec = json.loads(request.POST.get("spec", ""))
            except json.JSONDecodeError as error:
                messages.error(request, f"That isn't valid JSON ({error.msg}, line {error.lineno}).")
                return redirect("studio:image_job", pk=job.pk)
            if not isinstance(spec, dict):
                messages.error(request, "The content is one JSON object.")
                return redirect("studio:image_job", pk=job.pk)
            new = imagegen.again(job, request.user, spec=spec)
        messages.success(request, "Drawing the new version.")
        return redirect("studio:image_job", pk=new.pk)


def image_job_status(request, pk):
    if not request.user.has_perm(permissions.ACCESS):
        raise PermissionDenied
    job = get_object_or_404(ImageJob, pk=pk)
    return JsonResponse({"status": job.status, "active": job.is_open})


def image_job_download(request, pk, fmt):
    if not request.user.has_perm(permissions.ACCESS):
        raise PermissionDenied
    if fmt not in DOWNLOADS:
        raise Http404
    job = get_object_or_404(ImageJob.objects.select_related("image"), pk=pk)
    data = imagegen.file_bytes(job, fmt)
    if data is None:
        raise Http404("That file wasn't made for this image.")
    content_type, extension = DOWNLOADS[fmt]
    response = HttpResponse(data, content_type=content_type)
    stem = job.metrics.get("file_stem") or f"image-{job.pk}"
    response["Content-Disposition"] = f'attachment; filename="{stem}.{extension}"'
    return response
