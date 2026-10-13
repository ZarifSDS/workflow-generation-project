"""SVG and WebP images (user spec 2026-10-13): upload, page rendering, exports, SVG sandboxing."""

import io

import pytest
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from PIL import Image
from wagtail.images import get_image_model
from wagtail.images.forms import get_image_form

from apps.content import exports, publishing
from apps.studio import services
from apps.studio.middleware import SVG_CSP

pytestmark = pytest.mark.django_db

SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200" viewBox="0 0 400 200">'
    b'<rect width="400" height="200" fill="#0f766e"/><circle cx="200" cy="100" r="60" fill="#fff"/></svg>'
)


def _webp():
    buffer = io.BytesIO()
    Image.new("RGB", (640, 360), "teal").save(buffer, "WEBP")
    return buffer.getvalue()


def _upload(name, data, content_type, user):
    form_class = get_image_form(get_image_model())
    form = form_class({"title": name}, {"file": SimpleUploadedFile(name, data, content_type)}, user=user)
    return form


@pytest.mark.parametrize(
    "name, data, content_type",
    [("diagram.svg", SVG, "image/svg+xml"), ("photo.webp", _webp(), "image/webp")],
)
def test_image_form_accepts_svg_and_webp(name, data, content_type, admin_user):
    form = _upload(name, data, content_type, admin_user)
    assert form.is_valid(), form.errors
    image = form.save()
    assert image.is_svg() == name.endswith(".svg")
    assert (image.width, image.height) == ((400, 200) if image.is_svg() else (640, 360))
    rendition = image.get_rendition("max-1200x1200")
    assert rendition.url.endswith(".svg" if image.is_svg() else ".webp")


def test_image_form_still_rejects_other_types(admin_user):
    form = _upload("notes.txt", b"hello", "text/plain", admin_user)
    assert not form.is_valid()


def _svg_image():
    return get_image_model().objects.create(title="Diagram", file=ContentFile(SVG, name="diagram.svg"))


def test_svg_figure_renders_on_page_and_in_exports(admin_user, client):
    from docx import Document

    from apps.studio.models import ContentBrief

    brief = ContentBrief.objects.create(
        topic="MOC",
        pkeyword="management of change",
        region="US",
        content_type="seo_blog",
        created_by=admin_user,
    )
    run = services.create_run(brief, {}, user=admin_user)
    image = _svg_image()
    text = f'# Management of change\n\nIntro.\n\n![MOC flow](wagtail://image?id={image.pk} "The MOC flow.")\n'
    for key in ("draft", "cleanup"):
        step = run.steps.get(key=key)
        services.add_version(step, text)
        step.status = step.Status.APPROVED
        step.save()

    html = exports.html_export(run)
    assert ".svg" in html and 'alt="MOC flow"' in html
    document = Document(io.BytesIO(exports.docx_export(run)))
    assert len(document.inline_shapes) == 1  # the SVG, rasterised

    page = publishing.save_draft(run, admin_user).page
    page.get_latest_revision().publish()
    page.refresh_from_db()
    response = client.get(page.url)
    assert response.status_code == 200
    assert ".svg" in response.text and 'alt="MOC flow"' in response.text


def test_svg_is_rasterised_for_pillow():
    with Image.open(io.BytesIO(exports._image_bytes(_svg_image()))) as picture:
        assert picture.format == "PNG"
        assert picture.size == (exports.SVG_RASTER_WIDTH, exports.SVG_RASTER_WIDTH // 2)


def test_svg_responses_are_sandboxed(rf):
    from django.http import HttpResponse

    from apps.studio.middleware import SvgSandboxMiddleware

    svg = SvgSandboxMiddleware(lambda request: HttpResponse(SVG, content_type="image/svg+xml"))
    assert svg(rf.get("/media/original_images/diagram.svg"))["Content-Security-Policy"] == SVG_CSP
    png = SvgSandboxMiddleware(lambda request: HttpResponse(b"", content_type="image/png"))
    assert "Content-Security-Policy" not in png(rf.get("/media/a.png"))


def test_admin_pages_have_no_svg_csp(admin_client):
    response = admin_client.get(reverse("wagtailadmin_home"))
    assert response.get("Content-Security-Policy") != SVG_CSP


def test_caddy_sandboxes_svg_media():
    from pathlib import Path

    routes = (Path(__file__).resolve().parent.parent / "deploy" / "caddy" / "routes.caddy").read_text()
    assert f'header @svg Content-Security-Policy "{SVG_CSP}"' in routes
