"""JSON endpoints for the step-output editor (M9 phase 5): image upload, reference previews, embeds.

Every endpoint needs Content Studio access; uploads also need Wagtail's "add image" permission and go
through Wagtail's own image form, so the type and size limits (WAGTAILIMAGES_EXTENSIONS, 10 MB) apply.
CSRF is checked as for any POST (the editor sends the form's token).
"""

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from wagtail.images import get_image_model
from wagtail.images import get_permission_policy as image_policy
from wagtail.images.forms import get_image_form
from wagtail.models import Collection

from .. import permissions

PREVIEW_RENDITION = "max-800x600"
MAX_IDS = 50


def _denied(message="Your account can't do that.", status=403):
    return JsonResponse({"error": message}, status=status)


def _ids(request, name):
    values = [v for v in request.GET.get(name, "").split(",") if v.strip().isdigit()]
    return {int(v) for v in values[:MAX_IDS]}


def _image_json(image):
    rendition = image.get_rendition(PREVIEW_RENDITION)
    return {
        "id": image.pk,
        "title": image.title,
        "description": getattr(image, "description", "") or "",
        "url": rendition.url,
        "width": rendition.width,
        "height": rendition.height,
        "ref": f"wagtail://image?id={image.pk}",
    }


def upload_limits():
    """What the editor tells people before they drop a file."""
    return {
        "max_bytes": settings.WAGTAILIMAGES_MAX_UPLOAD_SIZE,
        "extensions": list(getattr(settings, "WAGTAILIMAGES_EXTENSIONS", [])),
    }


@require_POST
def upload_image(request):
    user = request.user
    if not user.has_perm(permissions.ACCESS) or not image_policy().user_has_permission(user, "add"):
        return _denied("Your account can't add images. Ask an admin for image permissions.")
    upload = request.FILES.get("file")
    if upload is None:
        return _denied("Choose an image to upload.", 400)
    decorative = request.POST.get("decorative") == "1"
    alt = "" if decorative else request.POST.get("alt", "").strip()
    if not decorative and not alt:
        return _denied("Add alt text, or mark the image as decorative.", 400)
    title = request.POST.get("title", "").strip() or upload.name.rsplit(".", 1)[0].replace("-", " ")[:255]
    collection = Collection.get_first_root_node()
    form_class = get_image_form(get_image_model())
    data = {"title": title, "collection": collection.pk, "description": alt}
    form = form_class(data, {"file": upload}, user=user)
    if not form.is_valid():
        errors = [str(error) for field_errors in form.errors.values() for error in field_errors]
        return _denied(" ".join(errors) or "That file can't be used.", 400)
    image = form.save(commit=False)
    image.uploaded_by_user = user
    image.save()
    return JsonResponse(_image_json(image), status=201)


def reference_data(image_ids=(), page_ids=(), document_ids=()):
    """{"images": {id: preview}, "pages": {id: {title, url}}, "documents": {id: {title, url}}}."""
    from wagtail.documents import get_document_model
    from wagtail.models import Page

    images = {
        str(image.pk): _image_json(image) for image in get_image_model().objects.filter(pk__in=image_ids)
    }
    pages = {
        str(page.pk): {"title": page.get_admin_display_title(), "url": page.url or ""}
        for page in Page.objects.filter(pk__in=page_ids).specific()
    }
    documents = {
        str(doc.pk): {"title": doc.title, "url": doc.url}
        for doc in get_document_model().objects.filter(pk__in=document_ids)
    }
    return {"images": images, "pages": pages, "documents": documents}


@require_GET
def references(request):
    """Titles and previews for referenced images, pages and documents (?image=1,2&page=3&document=4)."""
    if not request.user.has_perm(permissions.ACCESS):
        return _denied()
    return JsonResponse(
        reference_data(_ids(request, "image"), _ids(request, "page"), _ids(request, "document"))
    )


@require_GET
def embed_preview(request):
    """Title and thumbnail for a YouTube or Vimeo link (WAGTAILEMBEDS_FINDERS allows only those)."""
    if not request.user.has_perm(permissions.ACCESS):
        return _denied()
    from wagtail.embeds import embeds
    from wagtail.embeds.exceptions import EmbedException

    url = request.GET.get("url", "").strip()
    if not url.startswith(("https://", "http://")):
        return _denied("Paste a YouTube or Vimeo link.", 400)
    try:
        embed = embeds.get_embed(url)
    except EmbedException:
        return _denied("Only YouTube and Vimeo videos can be embedded, and the link must work.", 400)
    return JsonResponse(
        {
            "url": url,
            "title": embed.title or "",
            "thumbnail": embed.thumbnail_url or "",
            "provider": embed.provider_name or "",
        }
    )
