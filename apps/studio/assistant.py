"""The suggestions chat and the per-section Tune buttons on a step that's ready for review.

The view saves your message and a pending assistant message, then the worker runs `answer()`:
- suggest: the "chat" model answers with concrete suggestions; nothing changes.
- apply: the "chat" model returns the revised text, saved as a new version if it keeps the structure.
- tune: the "section_tune" model rewrites one section (H2, or H3 in a long section) towards a reading
  grade, saved as a new version if the grade goes down.
Model defaults are set under Settings › Default models.
"""

import logging

from django.db import transaction
from django.utils import timezone

from apps.ai.redact import redact
from apps.ai.types import ProviderError
from apps.quality import review

from . import prompting
from .models import ChatMessage, StepRun, StepVersion

logger = logging.getLogger(__name__)

HISTORY_MESSAGES = 10
CHAT_STEPS = {"site_crawl", "research", "outline", "draft", "review_edit", "cleanup", "localise"}
# Steps whose output is the article itself: reading grades, Tune and grade hints apply only here. Research,
# the site profile and the outline are planning documents, so their grades mean nothing.
ARTICLE_STEPS = {"draft", "review_edit", "cleanup", "localise"}


def can_chat(step):
    return step.key in CHAT_STEPS and step.status == StepRun.Status.READY and step.latest_version is not None


@transaction.atomic
def ask(step, user, text, action=ChatMessage.Action.SUGGEST, payload=None):
    """Save the request and queue the reply. Returns the pending assistant message."""
    from .services import enqueue_chat

    if not can_chat(step):
        raise ValueError("The chat is available while a step is waiting for review.")
    text = (text or "").strip()
    if not text:
        raise ValueError("Type what you'd like to change or ask.")
    if step.chat.filter(status__in=[ChatMessage.Status.PENDING, ChatMessage.Status.RUNNING]).exists():
        raise ValueError("Wait for the current reply before sending another request.")
    payload = {**(payload or {}), "base_version": step.latest_version.number}
    ChatMessage.objects.create(
        step=step,
        role=ChatMessage.Role.USER,
        action=action,
        content=text[:4000],
        payload=payload,
        created_by=user,
    )
    reply = ChatMessage.objects.create(
        step=step,
        role=ChatMessage.Role.ASSISTANT,
        action=action,
        payload=payload,
        status=ChatMessage.Status.PENDING,
        created_by=user,
    )
    enqueue_chat(reply)
    return reply


def tune_request(step, user, index, target):
    if step.key not in ARTICLE_STEPS:
        raise ValueError("Reading grades are tuned on the article (draft and later steps), not on plans.")
    rows = review.unit_rows(step.latest_version.content) if step.latest_version else []
    row = next((r for r in rows if r["index"] == index), None)
    if row is None:
        raise ValueError("That section no longer exists; reload the page.")
    if not row["graded"] or row["grade"] is None:
        raise ValueError(f"“{row['name']}” isn't graded prose, so it can't be tuned.")
    text = f"Tune “{row['name']}” to reading grade {target:g} (now {row['grade']})."
    return ask(
        step, user, text, ChatMessage.Action.TUNE, {"index": index, "target": target, "name": row["name"]}
    )


def _history(step, before):
    messages = list(
        step.chat.filter(pk__lt=before.pk, status=ChatMessage.Status.DONE).order_by("-pk")[:HISTORY_MESSAGES]
    )
    lines = [f"{m.get_role_display()}: {m.content.strip()[:1500]}" for m in reversed(messages)]
    return "\n\n".join(lines) or "(none)"


def _grades(step, text, target):
    if step.key not in ARTICLE_STEPS:
        return "(not measured: this step is a plan, not the article)"
    rows = [r for r in review.unit_rows(text, target) if r["graded"]]
    overall = review.article_metrics(text)["fkgl"]
    return f"- Whole article: {overall} (estimate)\n" + "\n".join(
        f"- {'  ' if r['level'] == 3 else ''}{r['name']}: "
        + (str(r["grade"]) if r["grade"] is not None else "too short")
        + (" (above target)" if r["over"] else "")
        + (
            f"; {len(r['hard']) + len(r['very_hard'])} hard sentence(s)"
            if r.get("hard") or r.get("very_hard")
            else ""
        )
        for r in rows
    )


def answer(message_id):
    """Worker entry point: fill in one pending assistant message. Never raises."""
    from .executors import _call_text, friendly_error
    from .services import add_version

    with transaction.atomic():
        reply = ChatMessage.objects.select_for_update().select_related("step__run__brief").get(pk=message_id)
        if reply.status != ChatMessage.Status.PENDING:
            return
        reply.status, reply.started_at = ChatMessage.Status.RUNNING, timezone.now()
        reply.save(update_fields=["status", "started_at"])

    step, brief = reply.step, reply.step.run.brief
    request = step.chat.filter(role=ChatMessage.Role.USER, pk__lt=reply.pk).order_by("-pk").first()
    version = step.latest_version
    try:
        if version is None or request is None:
            raise ValueError("There's nothing to work on yet.")
        context = prompting.context_for(
            step,
            {
                "step_label": step.label.lower(),
                "article": version.content,
                "version_number": version.number,
                "history": _history(step, request),
                "request": request.content,
                "grades": _grades(step, version.content, brief.fkgl),
            },
        )

        def call(prompt_name, extra=None, task="chat", max_tokens=4000):
            result = _call_text(
                step,
                prompting.render(prompt_name, {**context, **(extra or {})}),
                max_tokens=max_tokens,
                task=task,
            )
            reply.provider, reply.model = result.provider, result.model
            return result.text

        if reply.action == ChatMessage.Action.SUGGEST:
            reply.content = (
                call("chat").strip() or "The model returned an empty answer. Try again or rephrase."
            )
        elif reply.action == ChatMessage.Action.APPLY:
            revised = call("chat_apply", max_tokens=16000).strip()
            ok, reason = review.accept_rewrite(version.content, revised, min_ratio=0.5)
            if not ok:
                raise ValueError(f"The revision wasn't saved ({reason}). Try a narrower request.")
            saved = add_version(
                step,
                revised,
                provider=reply.provider,
                model=reply.model,
                note=f"From the suggestions chat: {request.content[:300]}",
            )
            reply.version_number = saved.number
            reply.content = (
                f"Applied as version {saved.number}. Compare it with version {version.number} under Versions."
            )
        else:  # tune
            target = float(reply.payload.get("target") or brief.fkgl)
            name = reply.payload.get("name", "section")
            text, before, after = review.tune_unit(
                version.content,
                int(reply.payload.get("index", -1)),
                target,
                brief.get_region_display(),
                lambda name, extra: call(name, extra, task="section_tune", max_tokens=8000),
            )
            saved = add_version(
                step,
                text,
                provider=reply.provider,
                model=reply.model,
                source=StepVersion.Source.AI,
                note=f"Tuned “{name}” towards reading grade {target:g}: {before} → {after}.",
                extra_metrics=_carry_review(version),
            )
            reply.version_number = saved.number
            reply.content = f"“{name}”: reading grade {before} → {after}. Saved as version {saved.number}."
        reply.status = ChatMessage.Status.DONE
    except (ProviderError, ValueError) as error:
        reply.status = ChatMessage.Status.FAILED
        reply.content = friendly_error(error) if isinstance(error, ProviderError) else str(error)
    except Exception as error:  # noqa: BLE001 - never leave a reply stuck in "working"
        logger.exception("Chat reply %s crashed", reply.pk)
        reply.status, reply.content = ChatMessage.Status.FAILED, redact(f"Unexpected error: {error!r}")[:1000]
    reply.finished_at = timezone.now()
    reply.save()


def _carry_review(version):
    """Keep Review and edit's report on a tuned version, so its split proposals stay available."""
    review_metrics = (version.metrics or {}).get("review")
    return {"review": review_metrics} if review_metrics else None
