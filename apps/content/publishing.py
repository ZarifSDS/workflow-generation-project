"""Turn an approved run into an ArticlePage draft in Wagtail's moderation workflow (M7)."""

import hashlib
import hmac
import json
import logging
from dataclasses import dataclass, field

import httpx
from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils.text import slugify
from wagtail.models import Site

from . import exports, markup
from .models import ArticleIndexPage, ArticlePage

logger = logging.getLogger(__name__)


PublishError = exports.ArticleError  # a problem the user can fix; shown on the run screen


@dataclass
class PublishResult:
    page: ArticlePage
    created: bool
    workflow: str = ""  # name of the workflow the page is in, if any
    workflow_started: bool = False
    warnings: list = field(default_factory=list)
    webhook: str = ""  # outcome of the optional n8n webhook


def article_index():
    """The "Articles" page under the site's home page, created on first use."""
    index = ArticleIndexPage.objects.first()
    if index:
        return index
    site = Site.objects.filter(is_default_site=True).first() or Site.objects.first()
    if site is None:
        raise PublishError("There is no Wagtail site to publish into. Create one under Settings › Sites.")
    index = ArticleIndexPage(title="Articles", slug="articles")
    site.root_page.add_child(instance=index)
    index.save_revision().publish()
    return index


def _unique_slug(index, wanted, page=None):
    base = slugify(wanted)[:80].strip("-") or "article"
    taken = set(index.get_children().exclude(pk=getattr(page, "pk", None)).values_list("slug", flat=True))
    slug, number = base, 2
    while slug in taken:
        slug, number = f"{base}-{number}", number + 1
    return slug


def admin_edit_url(page):
    return settings.WAGTAILADMIN_BASE_URL.rstrip("/") + reverse("wagtailadmin_pages:edit", args=[page.pk])


@transaction.atomic
def save_draft(run, user=None):
    """Create or update the run's ArticlePage as a draft revision and start moderation."""
    content = exports.article_content(run)
    meta = exports.article_meta(run, content)
    _, body = markup.split_h1(content.text)
    if not body.strip():
        raise PublishError("The approved article is empty.")

    warnings = []
    if count := markup.verify_markers(content.text):
        warnings.append(
            f"{count} claim{'s are' if count != 1 else ' is'} still marked [VERIFY]. "
            "Check them before approving the page."
        )
    if not meta["meta_description"]:
        warnings.append("No meta description is selected (Title and meta screen).")
    if content.hero is None:
        warnings.append("No approved hero image; the page has none.")

    index = article_index()
    page = ArticlePage.objects.filter(run=run).first()
    created = page is None
    if created:
        page = ArticlePage(live=False)
    else:
        page = page.get_latest_revision_as_object()

    page.title = meta["title"][:255]
    page.seo_title = meta["seo_title"][:255] if meta["seo_title"] != meta["title"] else ""
    page.search_description = meta["meta_description"]
    page.slug = _unique_slug(index, meta["slug"], None if created else page)
    page.body = markup.to_stream(body)
    page.hero_image = content.hero
    page.region = run.brief.region
    page.primary_keyword = run.brief.pkeyword
    page.run = run

    if created:
        index.add_child(instance=page)
    page.save_revision(user=user, log_action=True)

    result = PublishResult(page=page, created=created, warnings=warnings)
    workflow = page.get_workflow()
    if workflow:
        result.workflow = workflow.name
        if not page.workflow_in_progress:
            workflow.start(page, user)
            result.workflow_started = True
    return result


def notify_webhook(run, result):
    """POST the saved draft to STUDIO_PUBLISH_WEBHOOK_URL (e.g. an n8n Webhook node). Never raises."""
    url = settings.STUDIO_PUBLISH_WEBHOOK_URL
    if not url:
        return ""
    page = result.page
    payload = {
        "event": "article.draft_saved",
        "run_id": run.pk,
        "page_id": page.pk,
        "created": result.created,
        "title": page.title,
        "seo_title": page.seo_title,
        "slug": page.slug,
        "meta_description": page.search_description,
        "region": page.region,
        "primary_keyword": page.primary_keyword,
        "content_type": run.brief.content_type,
        "workflow": result.workflow,
        "admin_url": admin_edit_url(page),
        "warnings": result.warnings,
        "markdown": exports.markdown_export(run),
    }
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json", "User-Agent": settings.AI_USER_AGENT}
    if settings.STUDIO_WEBHOOK_SECRET:
        digest = hmac.new(settings.STUDIO_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        headers["X-Studio-Signature"] = f"sha256={digest}"
    try:
        response = httpx.post(url, content=body, headers=headers, timeout=20)
    except httpx.HTTPError as error:
        logger.warning("Publish webhook failed: %s", error)
        return f"The webhook couldn't be reached ({error.__class__.__name__})."
    if response.status_code >= 400:
        return f"The webhook answered HTTP {response.status_code}."
    return f"Sent to the webhook (HTTP {response.status_code})."


def publish(run, user=None):
    result = save_draft(run, user)  # committed before the webhook call
    result.webhook = notify_webhook(run, result)
    return result
