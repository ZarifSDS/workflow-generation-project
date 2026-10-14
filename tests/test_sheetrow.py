"""Guest-post intake from a pasted Guest Post Plan row (apps.studio.sheetrow). Rows here are invented examples
shaped like the real sheet: multi-line cells, URLs without a scheme, placeholders and word-count ranges."""

import pytest
from django.urls import reverse

from apps.studio import sheetrow
from apps.studio.models import ContentBrief

HEADER = "\t".join(
    [
        "#",
        "Website",
        "Type",
        "Status",
        "Published URLs",
        "Reference Guest Post(s)",
        "Proposed Article Topic / Title",
        "Primary Target Keyword",
        "Est. Vol / mo (US)*",
        "Supporting Keywords",
        "Anchor Text",
        "Backlink URL",
        "Rec. Word Count",
        "Angle / Notes & Requirements",
        "Blog Link",
    ]
)


def row(**cells):
    values = {
        "number": "12",
        "website": "example-safety-blog.co.uk",
        "type": "Paid",
        "status": "Approved",
        "published": "",
        "reference": "https://example-safety-blog.co.uk/blog/earlier-post",
        "title": "Why Workplace Risk Registers Fail an Inspection",
        "pkeyword": "risk register",
        "volume": "880",
        "skeywords": "risk assessment template\nhazard register",
        "anchor": "EHS risk management software\nsafety data sheet software",
        "url": "https://sdsmanager.com/uk/ehs-software/risk-management-software/\nsdsmanager.com/uk/",
        "wordcount": "1200-1300",
        "notes": "UK British English, no American spelling.",
        "blog_link": "",
    }
    values.update(cells)

    def quote(value):
        return f'"{value}"' if "\n" in value or "\t" in value else value

    return "\t".join(quote(values[key]) for key, _ in sheetrow.COLUMNS)


def test_a_row_under_its_header_fills_the_brief():
    result = sheetrow.parse(HEADER + "\n" + row())
    assert result.topic == "Why Workplace Risk Registers Fail an Inspection"
    assert result.pkeyword == "risk register"
    assert result.skeywords == ["risk assessment template", "hazard register"]
    assert result.site == "example-safety-blog.co.uk"
    assert result.site_domain == "https://example-safety-blog.co.uk/"
    assert result.anchors == [
        {
            "text": "EHS risk management software",
            "url": "https://sdsmanager.com/uk/ehs-software/risk-management-software/",
        },
        {"text": "safety data sheet software", "url": "https://sdsmanager.com/uk/"},
    ]
    assert result.wordcount == 1200
    assert result.region == "UK"
    assert result.source_reference == "Guest Post Plan sheet, entry #12"
    assert "Host requirements (sheet): UK British English" in result.notes
    assert "Recommended word count: 1200-1300." in result.notes
    assert "Placement: Paid, Approved." in result.notes
    assert "earlier-post" in result.notes
    assert any("https://" in w for w in result.warnings)
    assert any("range" in w for w in result.warnings)


def test_a_row_without_header_uses_the_sheet_order_with_or_without_the_number():
    with_number = sheetrow.parse(row())
    without = sheetrow.parse(row().split("\t", 1)[1])
    for result in (with_number, without):
        assert result.topic.startswith("Why Workplace")
        assert result.pkeyword == "risk register"
        assert len(result.anchors) == 2


def test_messy_cells_are_read_as_the_sheet_holds_them():
    result = sheetrow.parse(
        row(
            skeywords="Yes, ExactSDS, sds creation",
            anchor="SDS authoring software\nEHS management software",
            url="",
            wordcount="1755.0",
            notes="---",
            website="https://example-news.com",
        )
    )
    assert result.skeywords == ["ExactSDS", "sds creation"]
    assert result.anchors == [
        {"text": "SDS authoring software", "url": ""},
        {"text": "EHS management software", "url": ""},
    ]
    assert result.wordcount == 1755
    assert "Host requirements" not in result.notes
    assert result.region == ""
    assert any("No backlink URL for 'SDS authoring software'" in w for w in result.warnings)
    assert any("stray" in w for w in result.warnings)
    initial = result.initial()
    assert initial["anchors_text"] == "SDS authoring software |\nEHS management software |"
    assert initial["content_type"] == "outbound"
    assert "region" not in initial


def test_urls_split_by_a_space_pair_in_order():
    result = sheetrow.parse(row(url="https://sdsmanager.com/uk/a/ https://sdsmanager.com/uk/b/"))
    assert [a["url"] for a in result.anchors] == [
        "https://sdsmanager.com/uk/a/",
        "https://sdsmanager.com/uk/b/",
    ]


def test_a_linking_rule_in_the_anchor_cell_goes_to_the_notes():
    result = sheetrow.parse(
        row(
            anchor="no link will be provided but the author bio may cite SDS Manager",
            url="",
            notes="",
            website="example-academy.com",
        )
    )
    assert result.anchors == []
    assert "Host linking rule (sheet): no link will be provided" in result.notes
    assert any("linking rule" in w for w in result.warnings)


def test_us_product_urls_set_the_region():
    result = sheetrow.parse(
        row(
            website="example-news.com",
            notes="",
            url="https://sdsmanager.com/us/a/ https://sdsmanager.com/us/b/",
        )
    )
    assert result.region == "US"


@pytest.mark.parametrize(
    "text,message",
    [
        ("", "Paste a row"),
        (HEADER, "Only the header row"),
        ("just some words", "doesn't look like a sheet row"),
        (row() + "\n" + row(number="13"), "one article's row at a time"),
    ],
)
def test_unreadable_pastes_say_what_to_do(text, message):
    with pytest.raises(sheetrow.SheetRowError, match=message):
        sheetrow.parse(text)


def test_wizard_fills_from_a_pasted_row_without_saving(admin_client):
    response = admin_client.post(
        reverse("studio:brief_new"), {"action": "fill_from_row", "sheet_row": HEADER + "\n" + row()}
    )
    assert response.status_code == 200
    page = response.content.decode()
    assert 'value="Why Workplace Risk Registers Fail an Inspection"' in page
    assert (
        "EHS risk management software | https://sdsmanager.com/uk/ehs-software/risk-management-software/"
        in page
    )
    assert "Filled the brief from the sheet row" in page
    assert ContentBrief.objects.count() == 0
    form = response.context["form"]
    assert form["region"].value() == "UK"
    assert form["content_type"].value() == "outbound"


def test_wizard_keeps_the_paste_and_explains_when_it_cannot_read_it(admin_client):
    response = admin_client.post(
        reverse("studio:brief_new"), {"action": "fill_from_row", "sheet_row": "hello"}
    )
    assert response.status_code == 200
    page = response.content.decode()
    assert "doesn&#x27;t look like a sheet row" in page or "doesn't look like a sheet row" in page
    assert ">hello</textarea>" in page


def test_a_saved_brief_takes_the_pasted_anchors_over_its_own(admin_client):
    brief = ContentBrief.objects.create(
        topic="Old",
        pkeyword="old",
        content_type="outbound",
        site_domain="https://old.example/",
        anchors=[{"text": "old anchor", "url": "https://sdsmanager.com/us/"}],
    )
    response = admin_client.post(
        reverse("studio:brief_edit", args=[brief.pk]), {"action": "fill_from_row", "sheet_row": row()}
    )
    form = response.context["form"]
    assert "EHS risk management software" in form["anchors_text"].value()
    assert form["topic"].value().startswith("Why Workplace")
    brief.refresh_from_db()
    assert brief.topic == "Old"
