"""M9 phase 5: the editor's JSON endpoints (upload, references, embeds) and the writers' media rights."""

import io
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from PIL import Image
from wagtail.documents import get_document_model
from wagtail.images import get_image_model

pytestmark = pytest.mark.django_db

SVG = b'<svg xmlns="http://www.w3.org/2000/svg" width="40" height="20"><rect width="40" height="20"/></svg>'


def _png(name="photo.png"):
    buffer = io.BytesIO()
    Image.new("RGB", (64, 32), "teal").save(buffer, "PNG")
    return SimpleUploadedFile(name, buffer.getvalue(), "image/png")


def _client(*groups, csrf=False):
    user = get_user_model().objects.create_user(
        "-".join(groups).lower() or "nobody", password="unused-test-pw"
    )
    for group in groups:
        user.groups.add(Group.objects.get(name=group))
    client = Client(enforce_csrf_checks=csrf)
    client.force_login(user)
    return client


UPLOAD = reverse("studio:editor_upload_image")
REFS = reverse("studio:editor_refs")
EMBED = reverse("studio:editor_embed")


# ---- upload ----


def test_writer_uploads_an_image_with_alt_text():
    response = _client("Writers").post(UPLOAD, {"file": _png(), "alt": "Engineer at a panel"})
    assert response.status_code == 201, response.content
    data = response.json()
    image = get_image_model().objects.get(pk=data["id"])
    assert image.description == "Engineer at a panel" and image.title == "photo"
    assert data["ref"] == f"wagtail://image?id={image.pk}"
    assert data["url"].startswith("/media/images/") and data["width"] == 64


def test_svg_and_decorative_uploads():
    client = _client("Editors")
    svg = SimpleUploadedFile("diagram.svg", SVG, "image/svg+xml")
    response = client.post(UPLOAD, {"file": svg, "decorative": "1"})
    assert response.status_code == 201
    assert response.json()["url"].endswith(".svg")


def test_upload_needs_alt_text_unless_decorative():
    response = _client("Writers").post(UPLOAD, {"file": _png()})
    assert response.status_code == 400 and "alt text" in response.json()["error"]
    assert not get_image_model().objects.exists()


def test_upload_rejects_other_files():
    bad = SimpleUploadedFile("notes.txt", b"hello", "text/plain")
    response = _client("Writers").post(UPLOAD, {"file": bad, "alt": "x"})
    assert response.status_code == 400 and response.json()["error"]


def test_upload_size_limit(settings):
    settings.WAGTAILIMAGES_MAX_UPLOAD_SIZE = 100
    response = _client("Writers").post(UPLOAD, {"file": _png(), "alt": "x"})
    assert response.status_code == 400 and "too big" in response.json()["error"].lower()


def test_moderators_and_strangers_cant_upload():
    # Moderators can read the studio; uploading from the editor needs add-image rights *and* studio access.
    stranger = _client()
    assert stranger.post(UPLOAD, {"file": _png(), "alt": "x"}).status_code in (302, 403)
    operators = _client("Operators")
    assert operators.post(UPLOAD, {"file": _png(), "alt": "x"}).status_code == 403


def test_upload_requires_csrf():
    response = _client("Writers", csrf=True).post(UPLOAD, {"file": _png(), "alt": "x"})
    assert response.status_code == 403 and not get_image_model().objects.exists()


def test_upload_is_post_only():
    assert _client("Writers").get(UPLOAD).status_code == 405


# ---- references ----


def test_references_return_previews_and_titles():
    from apps.content import publishing

    image = get_image_model().objects.create(
        title="Diagram", file=ContentFile(SVG, name="d.svg"), description="A"
    )
    doc = get_document_model().objects.create(title="MOC form", file=ContentFile(b"%PDF-1.7", name="moc.pdf"))
    page = publishing.article_index()
    data = (
        _client("Writers")
        .get(REFS, {"image": f"{image.pk},x,999", "page": page.pk, "document": doc.pk})
        .json()
    )
    assert data["images"][str(image.pk)]["description"] == "A"
    assert data["pages"][str(page.pk)]["title"] == page.get_admin_display_title()
    assert data["documents"][str(doc.pk)]["title"] == "MOC form"
    assert "999" not in data["images"]


def test_references_need_studio_access():
    assert _client().get(REFS).status_code in (302, 403)


# ---- embeds ----


def test_embed_preview_uses_wagtail_embeds():
    fake = mock.Mock(
        title="MOC explained", thumbnail_url="https://i.ytimg.com/x.jpg", provider_name="YouTube"
    )
    with mock.patch("wagtail.embeds.embeds.get_embed", return_value=fake) as get_embed:
        data = _client("Writers").get(EMBED, {"url": "https://www.youtube.com/watch?v=abc123"}).json()
    get_embed.assert_called_once_with("https://www.youtube.com/watch?v=abc123")
    assert data == {
        "url": "https://www.youtube.com/watch?v=abc123",
        "title": "MOC explained",
        "thumbnail": "https://i.ytimg.com/x.jpg",
        "provider": "YouTube",
    }


def test_only_youtube_and_vimeo_are_embeddable(settings):
    from wagtail.embeds.finders import get_finders

    providers = [p for finder in get_finders() for p in getattr(finder, "_endpoints", {})]
    assert providers  # the oEmbed finder is configured with endpoints
    response = _client("Writers").get(EMBED, {"url": "https://twitter.com/x/status/1"})
    assert response.status_code == 400 and "YouTube" in response.json()["error"]


def test_embed_needs_a_web_link():
    assert _client("Writers").get(EMBED, {"url": "javascript:alert(1)"}).status_code == 400


# ---- permissions migration ----


def test_writers_can_add_and_choose_images_and_documents():
    from wagtail.documents import get_permission_policy as document_policy
    from wagtail.images import get_permission_policy as image_policy

    writer = get_user_model().objects.create_user("w", password="unused-test-pw")
    writer.groups.add(Group.objects.get(name="Writers"))
    for policy in (image_policy(), document_policy()):
        assert policy.user_has_permission(writer, "add")
        assert policy.user_has_permission(writer, "choose")
    # Wagtail lets owners change their own uploads, but not other people's.
    theirs = get_image_model().objects.create(title="Theirs", file=ContentFile(SVG, name="t.svg"))
    assert not image_policy().user_has_permission_for_instance(writer, "delete", theirs)
    assert not image_policy().user_has_permission_for_instance(writer, "change", theirs)


def test_workspace_passes_chooser_and_api_urls(admin_client):
    from apps.studio import services
    from apps.studio.models import ContentBrief, StepRun

    user = get_user_model().objects.get(username="admin")
    brief = ContentBrief.objects.create(topic="MOC", pkeyword="moc", created_by=user)
    run = services.create_run(brief, {}, user=user)
    step = run.steps.get(key="draft")
    services.add_version(step, "# Draft\n\nText.")
    step.status = StepRun.Status.READY
    step.save()
    html = admin_client.get(reverse("studio:run", args=[run.pk]) + "?step=draft").text
    for needle in (
        f'data-api-upload="{UPLOAD}"',
        f'data-api-refs="{REFS}"',
        f'data-api-embed="{EMBED}"',
        "data-chooser-page=",
        "wagtailimages/js/image-chooser-modal.js",
        'data-upload-max="10485760"',
        "svg",
    ):
        assert needle in html, needle
