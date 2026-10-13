"""M9 phase 6: comparing versions word by word and as rendered."""

import pytest
from django.urls import reverse

from apps.studio import diffing, services
from apps.studio.models import ContentBrief

OLD = "# Title\n\n" + "\n".join(f"Line {i}." for i in range(12)) + "\nThe old fox jumps.\n"
NEW = "# Title\n\n" + "\n".join(f"Line {i}." for i in range(12)) + "\nThe quick fox jumps high.\n"


def test_word_level_changes_and_counts():
    rows, stats = diffing.text_diff(OLD, NEW)
    change = next(row for row in rows if row.kind == "change")
    assert ("del", "old") in change.segments and ("add", "quick") in change.segments
    assert stats == {"added": 2, "removed": 1}


def test_long_unchanged_stretches_fold_and_keep_context():
    rows, _ = diffing.text_diff(OLD, NEW)
    kinds = [row.kind for row in rows]
    assert kinds[0] == "fold" and rows[0].count == 12  # title, blank and ten lines before the context
    assert kinds[1:3] == ["same", "same"]  # two lines of context before the change


def test_rewritten_lines_show_as_removed_then_added():
    rows, _ = diffing.text_diff(
        "Everything before this step is approved.", "Created the draft page under Articles."
    )
    assert [row.kind for row in rows] == ["del", "add"]


def test_identical_versions_have_no_rows():
    assert diffing.text_diff(OLD, OLD) == ([], {"added": 0, "removed": 0})


def test_whitespace_only_changes_inside_a_line_are_ignored_in_counts():
    _, stats = diffing.text_diff("A  word here", "A word here")
    assert stats == {"added": 0, "removed": 0}


def test_blocks_keep_faq_and_code_whole():
    text = "Intro\n\n:::faq\n### Q?\n\nA.\n:::\n\n```\ncode\n\nmore\n```\n\nEnd"
    assert diffing.split_blocks(text) == [
        "Intro",
        ":::faq\n### Q?\n\nA.\n:::",
        "```\ncode\n\nmore\n```",
        "End",
    ]


def test_rendered_diff_labels_blocks():
    blocks = diffing.rendered_diff("A\n\nB\n\nC", "A\n\nB changed\n\nD\n\nE", lambda text: f"<p>{text}</p>")
    assert [(b.kind, b.html) for b in blocks] == [
        ("same", "<p>A</p>"),
        ("change", "<p>B changed</p>"),
        ("change", "<p>D</p>"),
        ("add", "<p>E</p>"),
    ]
    assert blocks[1].old_html == "<p>B</p>"


@pytest.mark.django_db
def test_compare_view_text_and_rendered(admin_client, admin_user):
    brief = ContentBrief.objects.create(topic="T", pkeyword="t", created_by=admin_user)
    run = services.create_run(brief, {}, user=admin_user)
    step = run.steps.get(key="research")
    services.add_version(step, OLD + "\n<script>alert(1)</script>\n")
    services.add_version(step, NEW + "\n<script>alert(2)</script>\n\n## Added heading\n")
    url = reverse("studio:compare", args=[run.pk, "research", 1, 2])

    text = admin_client.get(url).text
    assert "<del>old</del>" in text and "<ins>quick</ins>" in text
    assert "12 unchanged lines" in text
    assert "<script>alert" not in text  # escaped in the text view

    rendered = admin_client.get(url + "?view=rendered").text
    assert "Added heading" in rendered and "s-rdiff__block--add" in rendered
    assert "<script>alert" not in rendered  # sanitised like any studio output
    assert 'aria-current="page">As it will look' in rendered
