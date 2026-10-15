"""Branded infographic templates (apps/quality/infographic.py; docs/infographic-audit.md)."""

import copy
import io

import pytest
from PIL import Image

from apps.quality import infographic
from apps.quality.infographic_examples import EXAMPLES

LOGO = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1503.89 500.91"><defs><style>.cls-1{fill:#626df9}'
    '</style></defs><rect class="cls-1" width="1503.89" height="500.91"/></svg>'
)


@pytest.fixture(autouse=True)
def logo(tmp_path, monkeypatch):
    """The real logo isn't in git (public repository); a placeholder with the same viewBox stands in."""
    path = tmp_path / "sds-manager-logo.svg"
    path.write_text(LOGO, encoding="utf-8")
    monkeypatch.setattr(infographic, "LOGO", path)
    infographic._logo_markup.cache_clear()
    yield
    infographic._logo_markup.cache_clear()


@pytest.mark.parametrize("kind", list(infographic.TEMPLATES))
def test_every_template_renders_the_live_examples_cleanly(kind):
    result = infographic.render(kind, EXAMPLES[kind])
    assert result.problems == [], result.problems
    assert result.width == 800 and 300 < result.height < 1200
    png = Image.open(io.BytesIO(result.png))
    webp = Image.open(io.BytesIO(result.webp))
    assert png.size == (1600, result.height * 2) and webp.width == 1200
    assert len(result.webp) < infographic.WEBP_BUDGET
    # Text is outlined (no font needed to open the SVG) and the logo is the vector logo.
    assert "<text" not in result.svg and 'viewBox="0 0 1503.89 500.91"' in result.svg
    assert 10 <= len(result.alt) <= 125 and EXAMPLES[kind]["title"].replace("**", "")[:20] in result.alt


def test_the_palette_passes_wcag_where_text_sits():
    c = infographic.contrast
    assert c(infographic.WHITE, infographic.PERI_DEEP) >= 4.5  # white on the action boxes and headers
    assert c(infographic.PERI_TEXT, infographic.LAVENDER) >= 4.5
    assert c(infographic.PERI_TEXT, infographic.WHITE) >= 4.5
    assert c(infographic.MUTED, infographic.WHITE) >= 4.5
    assert c(infographic.INK, infographic.YELLOW) >= 4.5
    assert c(infographic.INK, infographic.PERI_LIGHT) >= 4.5
    # The logo's own periwinkle gives white small text only about 4.2:1, which is why fills use PERI_DEEP.
    assert c(infographic.WHITE, infographic.PERI) < 4.5


def test_low_contrast_is_caught_on_what_was_drawn(monkeypatch):
    monkeypatch.setattr(infographic, "PERI_DEEP", infographic.PERI)
    result = infographic.render("decision", EXAMPLES["decision"])
    assert any("Contrast" in p["text"] and p["level"] == "block" for p in result.problems)


def test_text_that_does_not_fit_is_reported_not_cut():
    spec = copy.deepcopy(EXAMPLES["steps"])
    spec["steps"][0]["title"] = (
        "Assess the task, its hazards, its people, its equipment and every condition around it"
    )
    result = infographic.render("steps", spec)
    assert result.blocked and any("Too long for its box" in p["text"] for p in result.problems)
    long_title = dict(EXAMPLES["columns"], title="A " + "very long title " * 8)
    assert any("keep it to two" in p["text"] for p in infographic.render("columns", long_title).problems)


def test_counts_and_required_fields_are_checked_before_drawing():
    too_few = dict(EXAMPLES["bars"], bars=EXAMPLES["bars"]["bars"][:2])
    result = infographic.render("bars", too_few)
    assert result.blocked and result.png == b"" and "this layout takes 3 to 8" in result.problems[0]["text"]
    no_source = {k: v for k, v in EXAMPLES["part_to_whole"].items() if k != "source"}
    assert any(
        "source is missing" in p["text"] for p in infographic.render("part_to_whole", no_source).problems
    )
    wrong_total = copy.deepcopy(EXAMPLES["part_to_whole"])
    wrong_total["segments"][0]["value"] = 50
    assert any(
        "add up to 105%" in p["text"] for p in infographic.render("part_to_whole", wrong_total).problems
    )
    with pytest.raises(infographic.InfographicError, match="Unknown infographic type"):
        infographic.render("pie", {"title": "x"})


def test_house_style_is_fixed_and_reported():
    spec = dict(EXAMPLES["columns"], note="Heat and rain — they go in the safety column.")
    result = infographic.render("columns", spec)
    assert any("House style fixed" in p["text"] and p["level"] == "advise" for p in result.problems)
    assert not result.blocked


def test_figures_must_come_from_the_article():
    article = (
        "Hallowell (2021) found 45% of hazards are spotted in the briefing, "
        "35% are missed and 20% appear later."
    )
    spec = EXAMPLES["part_to_whole"]
    assert infographic.numbers_missing_from({"segments": spec["segments"]}, article) == []
    result = infographic.render(
        "part_to_whole",
        dict(spec, source="Hallowell, Professional Safety, 2021."),
        article=article.replace("20%", "a fifth"),
    )
    assert any("Not in the article: 20" in p["text"] for p in result.problems)


def test_a_missing_glyph_is_caught():
    # A character Inter lacks (house style strips emoji such as a snowman before drawing).
    spec = dict(EXAMPLES["steps"], subtitle="Five steps 中 for any task")
    assert any("no glyph" in p["text"] for p in infographic.render("steps", spec).problems)
