"""Admin theme (palette B): Wagtail-upgrade guard, WCAG contrast, branding and dashboard panels."""

import colorsys
import re
from pathlib import Path

import pytest
import wagtail
from django.contrib.auth.models import Group
from django.urls import reverse

THEME = Path(__file__).resolve().parents[1] / "apps" / "brand" / "static" / "brand" / "theme.css"
WAGTAIL_CSS = Path(wagtail.__file__).parent / "admin" / "static" / "wagtailadmin" / "css" / "core.css"


def test_every_overridden_wagtail_variable_still_exists():
    """If a Wagtail upgrade renames a variable, the theme would silently stop applying."""
    ours = set(re.findall(r"(--w-[a-z0-9-]+)\s*:", THEME.read_text(encoding="utf-8")))
    theirs = set(re.findall(r"(--w-[a-z0-9-]+)\s*:", WAGTAIL_CSS.read_text(encoding="utf-8")))
    assert ours, "no Wagtail variables found in theme.css"
    assert ours <= theirs, f"not defined by Wagtail any more: {sorted(ours - theirs)}"


def _luminance(hex_colour):
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(a, b):
    high, low = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _hsl(hue, saturation, lightness):
    r, g, b = colorsys.hls_to_rgb(hue / 360, lightness / 100, saturation / 100)
    return "#{:02x}{:02x}{:02x}".format(*(round(c * 255) for c in (r, g, b)))


ACCENT_LIGHT = _hsl(177, 56, 28)  # --w-color-secondary from the theme's HSL roots
SIDEBAR = _hsl(60, 6, 13)  # --w-color-primary


@pytest.mark.parametrize(
    ("label", "foreground", "background", "minimum"),
    [
        ("light: text on page", "#1c1c1a", "#f5f5f3", 4.5),
        ("light: meta text on page", "#66665f", "#f5f5f3", 4.5),
        ("light: meta text on field", "#66665f", "#ffffff", 4.5),
        ("light: link on page", ACCENT_LIGHT, "#f5f5f3", 4.5),
        ("light: button text", "#ffffff", ACCENT_LIGHT, 4.5),
        ("light: menu text on sidebar", "#ffffff", SIDEBAR, 4.5),
        ("light: focus ring on page", "#2b8a84", "#f5f5f3", 3.0),
        ("light: focus ring on sidebar", "#2b8a84", SIDEBAR, 3.0),
        ("dark: text on page", "#e8e8e4", "#141413", 4.5),
        ("dark: text on field", "#e8e8e4", "#1d1d1b", 4.5),
        ("dark: meta text on field", "#a3a39c", "#1d1d1b", 4.5),
        ("dark: link on field", "#5fb3ac", "#1d1d1b", 4.5),
        ("dark: button text", "#141413", "#5fb3ac", 4.5),
        ("dark: focus ring on page", "#e9b949", "#141413", 3.0),
    ],
)
def test_palette_contrast(label, foreground, background, minimum):
    assert _contrast(foreground, background) >= minimum, f"{label}: {_contrast(foreground, background):.2f}:1"


@pytest.mark.django_db
def test_theme_loads_on_sign_in_page_without_rebranding(client):
    html = client.get(reverse("wagtailadmin_login")).text
    assert "brand/theme.css" in html
    assert "Content Studio" not in html  # Wagtail's own wording and logo stay


@pytest.mark.django_db
def test_dashboard_has_studio_panels(client, django_user_model):
    user = django_user_model.objects.create_user("writer", password="unused-test-password")
    user.groups.add(Group.objects.get(name="Writers"))
    client.force_login(user)
    html = client.get(reverse("wagtailadmin_home")).text
    assert "Waiting for your review" in html
    assert "Recent runs" not in html or "studio-recent-runs" in html
