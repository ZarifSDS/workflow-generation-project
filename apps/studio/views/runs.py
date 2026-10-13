import hashlib

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse

from apps.ai import catalog
from apps.quality import house, review

from .. import assistant, diffing, permissions, services
from ..models import ChatMessage, GenerationRun, StepRun
from . import editor_api
from .common import StudioPage


class RunListView(StudioPage):
    template_name = "studio/run_list.html"
    page_title = "Runs"

    def get_breadcrumbs_items(self):
        return super().get_breadcrumbs_items() + [{"url": "", "label": "Runs"}]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        runs = GenerationRun.objects.select_related("brief").prefetch_related("steps")
        status = self.request.GET.get("status", "")
        if status in GenerationRun.Status.values:
            runs = runs.filter(status=status)
        context.update(runs=runs, status=status, statuses=GenerationRun.Status.choices)
        return context


def _checks(version, brief):
    """Summarise a version's metrics for the checks panel."""
    m = version.metrics if version else {}
    if not m:
        return None
    pk = m.get("pkeyword", {})
    red_flags = sum((m.get("accuracy_hints") or {}).get("red_flags", {}).values())
    return {
        "pk_title": pk.get("in_h1"),
        "pk_first100": pk.get("in_first_100_words"),
        "pk_headings": pk.get("in_headings", 0),
        "skeywords": m.get("skeywords", {}),
        "verify": m.get("verify_markers", 0),
        "red_flags": red_flags,
        "meta_narration": m.get("meta_narration", 0),
        "spelling": m.get("wrong_spelling_variant", {}),
        "fkgl": m.get("fkgl"),
        "sections": [s for s in m.get("section_fkgl", []) if s.get("fkgl") is not None],
        "target": float(brief.fkgl),
        "words": m.get("word_count"),
    }


def _export_links(run):
    """(url, label) download links for the approved article, its localised variant and the hero."""
    from apps.content import exports

    def url(fmt, variant=""):
        link = reverse("studio:run_export", args=[run.pk, fmt])
        return f"{link}?variant={variant}" if variant else link

    try:
        content = exports.article_content(run)
    except exports.ArticleError:
        return []
    links = [(url(fmt), label) for fmt, label in (("md", "Markdown"), ("html", "HTML"), ("docx", "Word"))]
    if content.hero is not None:
        links.append((url("webp"), "Hero WebP (720×405)"))
    try:
        exports.article_content(run, "localised")
        region = run.brief.localise_to
        links += [
            (url("md", "localised"), f"Markdown ({region})"),
            (url("docx", "localised"), f"Word ({region})"),
        ]
    except exports.ArticleError:
        pass
    return links


def _editor_refs(version):
    """Previews and titles for what the version references, for the visual editor (editor_api shape)."""
    from apps.content import dialect, markup

    ids = {"image": set(), "page": set(), "document": set()}
    for url in markup.REF_DESTINATION.findall(version.content if version else ""):
        kind, params = dialect.parse_ref(url) or (None, {})
        if kind in ids and params.get("id", "").isdigit():
            ids[kind].add(int(params["id"]))
    return editor_api.reference_data(ids["image"], ids["page"], ids["document"])


def _hero(version):
    """Hero branding results for the checks panel, with the unbranded photo."""
    from wagtail.images import get_image_model

    hero = (version.metrics or {}).get("hero") if version else None
    if not hero:
        return None
    photo = get_image_model().objects.filter(pk=hero.get("photo_image_id")).first()
    return {**hero, "photo": photo if hero.get("branded") else None}


class RunWorkspaceView(StudioPage):
    template_name = "studio/run_workspace.html"

    def dispatch(self, request, *args, **kwargs):
        self.run = get_object_or_404(GenerationRun.objects.select_related("brief"), pk=kwargs["pk"])
        self.page_title = self.run.brief.topic
        return super().dispatch(request, *args, **kwargs)

    def get_breadcrumbs_items(self):
        return super().get_breadcrumbs_items() + [
            {"url": reverse("studio:runs"), "label": "Runs"},
            {"url": "", "label": self.run.brief.topic},
        ]

    def selected_step(self):
        steps = self.run.steps.all()
        key = self.request.GET.get("step") or self.request.POST.get("step")
        if key:
            step = steps.filter(key=key).first()
            if step:
                return step
        return self.run.current_step

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        step = self.selected_step()
        user = self.request.user
        version = step.latest_version if step else None
        versions = list(step.versions.order_by("-number")) if step else []
        kind = step.definition.kind if step else "text"
        can_review = bool(
            step
            and step.status == StepRun.Status.READY
            and self.run.status != GenerationRun.Status.REJECTED
            and permissions.can_review(user, step)
        )
        context.update(
            run=self.run,
            brief=self.run.brief,
            steps=self.run.steps.all(),
            step=step,
            version=version,
            versions=versions,
            first_version=versions[-1] if versions else None,
            checks=_checks(version, self.run.brief)
            if step and step.key in assistant.ARTICLE_STEPS and kind != "image"
            else None,
            sop=(version.metrics or {}).get("sop") if version else None,
            hero=_hero(version) if kind == "image" else None,
            article_page=getattr(self.run, "article_page", None) if step and step.key == "publish" else None,
            exports=_export_links(self.run)
            if step and step.key == "publish" and user.has_perm(permissions.EDITING)
            else None,
            model_groups=catalog.grouped(kind) if kind in ("text", "image") else [],
            current_model_key=f"{step.provider}::{step.model}" if step and step.model else "",
            can_review=can_review,
            # Text output (the model steps and Final cleanup) can be edited; the hero and Publish can't.
            can_edit=can_review and kind != "image" and step.key != "publish",
            editor_refs=_editor_refs(version) if can_review and kind != "image" else None,
            upload_limits=editor_api.upload_limits(),
            user_can_act=bool(step and permissions.can_review(user, step)),
            user_can_retry=bool(step and permissions.can_act(user, step, "retry")),
            user_can_recover=bool(
                step and step.status == StepRun.Status.RUNNING and user.has_perm(permissions.OPERATE)
            ),
            review_role=permissions.describe_role(step) if step else "",
            has_metadata=self.run.metadata_options.exists(),
            review=(version.metrics or {}).get("review") if version else None,
            quality=(version.metrics or {}).get("quality") if version else None,
            typical=(
                catalog.find(step.provider, step.model).typical_seconds
                if step and catalog.find(step.provider, step.model)
                else None
            ),
            run_active=self.run.steps.filter(
                status__in=[StepRun.Status.QUEUED, StepRun.Status.RUNNING]
            ).exists()
            or _open_chat(self.run).exists(),
            chat=list(step.chat.select_related("created_by")) if step else [],
            can_chat=bool(step and assistant.can_chat(step) and permissions.can_review(user, step)),
        )
        if version and kind == "text" and step.key in assistant.ARTICLE_STEPS:
            markers = house.find_markers(version.content)
            context.update(
                section_rows=review.unit_rows(version.content, self.run.brief.fkgl),
                article_metrics=review.article_metrics(version.content),
                markers=markers,
                has_sources=any(m["kind"] == "SRC" for m in markers),
            )
        return context

    def post(self, request, *args, **kwargs):
        step = self.selected_step()
        action = request.POST.get("action")
        url = (
            f"{reverse('studio:run', args=[self.run.pk])}?step={step.key}" if step else reverse("studio:runs")
        )
        if step is None or not permissions.can_act(request.user, step, action):
            messages.error(
                request,
                "Your account can't do that on this step"
                + (f"; it's for {permissions.describe_role(step)}." if step else "."),
            )
            return redirect(url)
        # The version the page showed; edits and approvals are refused if a newer one was saved since.
        base_version = request.POST.get("base_version")
        try:
            if action == "recover":
                services.recover_step(step, request.user)
                messages.success(request, f"Marked {step.label.lower()} as failed. Retry it when ready.")
            elif action == "approve":
                services.approve_step(step, request.user, base_version=base_version)
                messages.success(request, f"Approved {step.label.lower()}.")
            elif action == "edit_approve":
                services.approve_step(
                    step,
                    request.user,
                    edited_content=request.POST.get("content", ""),
                    base_version=base_version,
                )
                messages.success(request, f"Saved your edit and approved {step.label.lower()}.")
            elif action == "save_version":
                saved = services.save_edit(
                    step, request.user, request.POST.get("content", ""), base_version=base_version
                )
                if saved:
                    messages.success(request, f"Saved your edit as version {saved.number}.")
                else:
                    messages.info(request, "Nothing changed, so no new version was saved.")
            elif action == "regenerate":
                services.request_regenerate(step, request.POST.get("model", ""), request.POST.get("note", ""))
                messages.success(request, _queued_message(step, "is queued with the chosen model."))
            elif action in ("chat_suggest", "chat_apply"):
                kind = ChatMessage.Action.APPLY if action == "chat_apply" else ChatMessage.Action.SUGGEST
                assistant.ask(step, request.user, request.POST.get("message", ""), kind)
                messages.success(request, "Sent. The reply appears below the text when it's ready.")
                return redirect(f"{url}#chat")
            elif action == "tune":
                try:
                    index, target = (
                        int(request.POST.get("section", "")),
                        float(request.POST.get("target", "")),
                    )
                except ValueError:
                    raise ValueError("Choose a section and a reading grade between 4 and 16.") from None
                if not 4 <= target <= 16:
                    raise ValueError("Choose a reading grade between 4 and 16.")
                assistant.tune_request(step, request.user, index, target)
                messages.success(request, "Tuning the section. The result appears in the chat below.")
                return redirect(f"{url}#chat")
            elif action == "accept_splits":
                services.accept_splits(step, request.user, request.POST.getlist("split"))
                messages.success(request, "Applied the chosen splits as a new version.")
            elif action == "retry":
                services.retry_step(step)
                messages.success(request, _queued_message(step, "is queued again."))
            elif action == "rerun":
                services.rerun_step(step)
                messages.success(request, f"{step.label} is queued again.")
            elif action == "strip_sources":
                saved = services.strip_sources(step, request.user)
                messages.success(request, f"Stripped the source markers as version {saved.number}.")
            elif action == "send_back":
                feedback = request.POST.get("feedback", "").strip()
                if not feedback:
                    raise ValueError("Say what should change, so the model can act on it.")
                if request.POST.get("how") == "edit":
                    assistant.ask(step, request.user, feedback, ChatMessage.Action.APPLY)
                    messages.success(
                        request, "Applying your feedback as targeted edits; the new version appears here."
                    )
                    return redirect(f"{url}#chat")
                services.request_regenerate(step, request.POST.get("model", ""), feedback)
                messages.success(request, _queued_message(step, "is being regenerated with your feedback."))
            elif action in ("reopen", "reopen_regenerate"):
                reason = services.reopen_run(self.run)
                step.refresh_from_db()
                if action == "reopen_regenerate" and step.definition.profile:
                    services.request_regenerate(step, request.POST.get("model", ""), reason)
                    queued = _queued_message(
                        step, "is being regenerated with the rejection reason as feedback."
                    )
                    messages.success(request, f"Reopened the run. {queued}")
                else:
                    messages.success(
                        request, "Reopened the run. Rejected steps are waiting for review again."
                    )
            elif action == "reject":
                reason = request.POST.get("reason", "").strip()
                if not reason:
                    messages.error(request, "Give a reason for rejecting the run.")
                    return redirect(url)
                services.reject_run(self.run, request.user, reason)
                messages.warning(request, "Run rejected.")
            else:
                messages.error(request, "Unknown action.")
        except ValueError as error:
            messages.error(request, str(error))
        return redirect(url)


def _open_chat(run):
    return ChatMessage.objects.filter(
        step__run=run, status__in=[ChatMessage.Status.PENDING, ChatMessage.Status.RUNNING]
    )


def _queued_message(step, queued_text):
    if step.status == StepRun.Status.PENDING:
        blocker = services.blocking_step(step)
        waiting_for = f"{blocker.label.lower()} is approved" if blocker else "the step before it is approved"
        return f"Saved. {step.label} starts with this model once {waiting_for}."
    return f"{step.label} {queued_text}"


class VersionCompareView(StudioPage):
    template_name = "studio/version_compare.html"
    page_title = "Compare versions"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        run = get_object_or_404(GenerationRun, pk=self.kwargs["pk"])
        step = get_object_or_404(StepRun, run=run, key=self.kwargs["step"])
        try:
            old = step.versions.get(number=self.kwargs["a"])
            new = step.versions.get(number=self.kwargs["b"])
        except step.versions.model.DoesNotExist as error:
            raise Http404("That version is no longer kept.") from error
        view = "rendered" if self.request.GET.get("view") == "rendered" else "text"
        rows, stats = diffing.text_diff(old.content, new.content)
        blocks = []
        if view == "rendered":
            from django.utils.safestring import mark_safe

            from apps.content.markup import WagtailResolver, markdown_to_html

            resolver = WagtailResolver()

            def render(markdown):
                return mark_safe(markdown_to_html(markdown, resolver))  # noqa: S308 - sanitised by nh3

            blocks = diffing.rendered_diff(old.content, new.content, render)
        context.update(run=run, step=step, old=old, new=new, rows=rows, stats=stats, blocks=blocks, view=view)
        return context

    def get_breadcrumbs_items(self):
        run_url = reverse("studio:run", args=[self.kwargs["pk"]])
        return super().get_breadcrumbs_items() + [
            {"url": reverse("studio:runs"), "label": "Runs"},
            {"url": f"{run_url}?step={self.kwargs['step']}", "label": "Run"},
            {"url": "", "label": "Compare versions"},
        ]


def run_status(request, pk):
    """Polled by the run workspace while steps are queued or running."""
    if not request.user.has_perm(permissions.ACCESS):
        raise PermissionDenied
    run = get_object_or_404(GenerationRun, pk=pk)
    steps = [
        {"key": s.key, "status": s.status, "started_at": s.started_at.isoformat() if s.started_at else None}
        for s in run.steps.all()
    ]
    open_chat = list(_open_chat(run).values_list("pk", flat=True))
    signature = hashlib.sha1(
        "|".join(f"{s['key']}:{s['status']}" for s in steps).encode()
        + run.status.encode()
        + f"chat:{open_chat}".encode()
    ).hexdigest()
    active = bool(open_chat) or any(
        s["status"] in (StepRun.Status.QUEUED, StepRun.Status.RUNNING) for s in steps
    )
    return JsonResponse({"run": run.status, "steps": steps, "signature": signature, "active": active})


EXPORTS = {
    "md": ("text/markdown; charset=utf-8", "md"),
    "html": ("text/html; charset=utf-8", "html"),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "docx"),
    "webp": ("image/webp", "webp"),
}


def run_export(request, pk, fmt):
    """Download the approved article (or its localised variant, ?variant=localised)."""
    from apps.content import exports

    if not request.user.has_perm(permissions.EDITING):
        raise PermissionDenied
    run = get_object_or_404(GenerationRun.objects.select_related("brief"), pk=pk)
    if fmt not in EXPORTS:
        raise Http404
    variant = "localised" if request.GET.get("variant") == "localised" else "final"
    try:
        if fmt == "webp":
            body, name = exports.hero_webp(run), exports.filename(run)
        else:
            builder = {
                "md": exports.markdown_export,
                "html": exports.html_export,
                "docx": exports.docx_export,
            }
            body, name = builder[fmt](run, variant), exports.filename(run, variant)
    except exports.ArticleError as error:
        messages.error(request, str(error))
        return redirect(f"{reverse('studio:run', args=[run.pk])}?step=publish")
    content_type, extension = EXPORTS[fmt]
    response = HttpResponse(body, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{name}.{extension}"'
    return response
