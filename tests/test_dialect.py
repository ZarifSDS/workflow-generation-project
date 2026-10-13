"""The studio's Markdown dialect (ADR 0007): rendering, references, sanitising and helpers."""

from pathlib import Path

import pytest

from apps.content import dialect, markup

FIXTURES = Path(__file__).parent / "fixtures" / "dialect"
ARTICLE = (FIXTURES / "article.md").read_text(encoding="utf-8")


class FakeResolver(dialect.Resolver):
    def images(self, ids):
        return (
            {42: dialect.ResolvedImage("/media/images/engineer.max-1200x1200.jpg", 1200, 675)}
            if 42 in ids
            else {}
        )

    def pages(self, ids):
        return {3: "/home/articles/sds/"} if 3 in ids else {}

    def documents(self, ids):
        return {7: "/documents/7/moc-template.docx"} if 7 in ids else {}


@pytest.fixture
def rendered():
    return markup.render(ARTICLE, FakeResolver())


def test_heading_ids_explicit_auto_and_unique():
    html, _ = markup.render(
        "## What counts {#what-counts}\n\n## Who signs off\n\n### Who signs off\n\n## Café rules"
    )
    assert '<h2 id="what-counts">What counts</h2>' in html
    assert '<h2 id="who-signs-off">' in html
    assert '<h3 id="who-signs-off-2">' in html
    assert '<h2 id="cafe-rules">' in html
    assert "{#" not in html


def test_slug_rule():
    assert dialect.slugify("  Safety Data Sheets: 2026 update! ") == "safety-data-sheets-2026-update"
    assert dialect.slugify("Über Größe") == "uber-groe"
    assert dialect.slugify("!!!") == "section"


def test_inline_marks(rendered):
    html, _ = rendered
    assert "<u>temporary bypasses</u>" in html
    assert "<s>Like-for-like replacements</s>" in html
    assert "<strong>process conditions</strong>" in html


def test_links_of_every_type_resolve(rendered):
    html, warnings = rendered
    assert 'href="https://www.osha.gov/process-safety-management"' in html
    assert 'href="/home/articles/sds/"' in html
    assert 'href="/documents/7/moc-template.docx"' in html
    assert 'href="#what-counts"' in html
    assert 'href="mailto:safety@example.com"' in html
    assert 'href="tel:+441234567890"' in html
    assert "wagtail://" not in html
    assert warnings == []


def test_image_becomes_figure_with_caption_and_alt(rendered):
    html, _ = rendered
    assert "<figure>" in html
    assert 'alt="Engineer reviewing a change request at a control panel"' in html
    assert 'src="/media/images/engineer.max-1200x1200.jpg"' in html
    assert 'width="1200"' in html and 'loading="lazy"' in html
    assert "<figcaption>Every change needs a named reviewer.</figcaption>" in html


def test_embed_becomes_a_link_figure_not_an_iframe(rendered):
    html, _ = rendered
    assert 'data-embed="https://www.youtube.com/watch?v=abc123"' in html
    assert '<a href="https://www.youtube.com/watch?v=abc123"' in html
    assert "<iframe" not in html


def test_faq_block(rendered):
    html, warnings = rendered
    assert '<section data-block="faq">' in html
    assert "<h3" in html and "Does a temporary change need MOC?" in html
    assert "an end date" in html
    assert not any("FAQ" in warning for warning in warnings)


def test_unclosed_faq_is_reported():
    _, warnings = markup.render(":::faq\n### Question?\n\nAnswer.")
    assert any("no closing" in warning for warning in warnings)


def test_decorative_image_has_empty_alt():
    html, warnings = markup.render('![](wagtail://image?id=42&decorative=1 "Skyline")', FakeResolver())
    assert 'alt=""' in html and 'data-decorative="1"' in html
    assert warnings == []


def test_missing_alt_text_is_reported():
    _, warnings = markup.render("![](wagtail://image?id=42)", FakeResolver())
    assert any("no alt text" in warning for warning in warnings)


def test_unresolvable_references_degrade_and_warn():
    html, warnings = markup.render(
        'See [the old page](wagtail://page?id=999).\n\n![Gone](wagtail://image?id=998 "Caption")',
        FakeResolver(),
    )
    assert "See the old page." in html
    assert "<figure" not in html and "Caption" not in html
    assert len(warnings) == 2


def test_stream_mode_keeps_references():
    html, _ = markup.render(ARTICLE, mode="stream")
    assert 'href="wagtail://page?id=3"' in html
    assert 'src="wagtail://image?id=42"' in html


@pytest.mark.parametrize(
    "hostile",
    [
        "<script>alert(1)</script>",
        '<iframe src="https://evil.example"></iframe>',
        '<img src="x" onerror="alert(1)">',
        "[click](javascript:alert(1))",
        '![x](javascript:alert(1) "t")',
        '<img src="https://tracker.example/pixel.gif">',
        '<img src="//tracker.example/pixel.gif">',
        "![x](https://tracker.example/pixel.gif)",
    ],
)
def test_hostile_input_is_neutralised(hostile):
    for mode in ("html", "stream"):
        html, _ = markup.render(hostile, FakeResolver(), mode)
        assert "<script" not in html and "<iframe" not in html
        assert "onerror" not in html and "javascript:" not in html
        assert "tracker.example" not in html.split("<a", 1)[0] and "<img" not in html


def test_verify_markers_survive_escaping():
    assert markup.verify_markers("One [VERIFY] and an escaped \\[VERIFY\\].") == 2


def test_strip_dialect_for_metrics():
    stripped = markup.strip_dialect(ARTICLE)
    assert "{#what-counts}" not in stripped and "## What counts a change" not in stripped
    assert "## What counts as a change" in stripped
    assert "wagtail://" not in stripped
    assert "our SDS page" in stripped
    assert ":::" not in stripped and "++" not in stripped


def test_references_match_wagtails_own_markdown_format():
    """Our dialect reads the wagtail:// references Wagtail 8 itself writes."""
    from wagtail.admin.rich_text.converters.markdown_db import wagtail_ref

    page, image = wagtail_ref("page", id=3), wagtail_ref("image", id=42, format="fullwidth")
    media = wagtail_ref("media", url="https://www.youtube.com/watch?v=abc123")
    assert dialect.parse_ref(page) == ("page", {"id": "3"})
    assert dialect.parse_ref(image) == ("image", {"id": "42", "format": "fullwidth"})
    assert dialect.parse_ref(media) == ("media", {"url": "https://www.youtube.com/watch?v=abc123"})
    html, _ = markup.render(f"[SDS]({page})\n\n![Engineer]({image})", FakeResolver())
    assert 'href="/home/articles/sds/"' in html and "engineer.max-1200x1200.jpg" in html
