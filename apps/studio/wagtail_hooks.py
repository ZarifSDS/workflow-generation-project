import copy

from django.templatetags.static import static
from django.urls import include, path, reverse
from django.utils.html import format_html
from wagtail import hooks
from wagtail.admin.menu import Menu, MenuItem, SubmenuMenuItem
from wagtail.admin.viewsets.model import ModelViewSet

from . import urls as studio_urls
from .models import BriefPreset
from .services import review_count

# Other studio features register their menu items on this hook, so the "Content Studio"
# submenu grows without editing this file.
studio_menu = Menu(
    register_hook_name="register_studio_menu_item",
    construct_hook_name="construct_studio_menu",
)


class PresetViewSet(ModelViewSet):
    model = BriefPreset
    icon = "form"
    menu_label = "Presets"
    add_to_admin_menu = False
    url_prefix = "studio/presets"
    url_namespace = "studio_presets"
    list_display = ["name", "content_type", "region", "fkgl"]
    list_filter = ["content_type", "region"]
    search_fields = ["name"]
    form_fields = [
        "name",
        "content_type",
        "region",
        "fkgl",
        "wordcount",
        "audience",
        "comprehension",
        "cta_style",
        "narrative_mode",
    ]
    inspect_view_enabled = True


preset_viewset = PresetViewSet("studio_presets")


@hooks.register("register_admin_viewset")
def register_preset_viewset():
    return preset_viewset


@hooks.register("register_admin_urls")
def register_studio_urls():
    return [path("studio/", include(studio_urls, namespace="studio"))]


@hooks.register("register_admin_menu_item")
def register_studio_menu():
    return SubmenuMenuItem(
        "Content Studio", studio_menu, icon_name="rocket", name="content-studio", order=150
    )


@hooks.register("construct_main_menu")
def add_review_badge(request, menu_items):
    """Show how many steps wait for review, e.g. "Content Studio (2)" (admin-only notifications)."""
    count = review_count()
    if not count:
        return
    for index, item in enumerate(menu_items):
        if getattr(item, "name", "") == "content-studio":
            badged = copy.copy(item)
            badged.label = f"Content Studio ({count})"
            menu_items[index] = badged


STUDIO_ITEMS = [
    ("Dashboard", "studio:dashboard", "home", "studio-dashboard"),
    ("New brief", "studio:brief_new", "plus", "studio-new-brief"),
    ("Briefs", "studio:briefs", "doc-full", "studio-briefs"),
    ("Runs", "studio:runs", "list-ul", "studio-runs"),
    ("Presets", "studio_presets:index", "form", "studio-presets"),
    ("Models and providers", "studio:providers", "cogs", "studio-providers"),
]


def _make_item(label, url_name, icon, name, order):
    @hooks.register("register_studio_menu_item")
    def register():
        return MenuItem(label, reverse(url_name), icon_name=icon, name=name, order=order)

    return register


for _order, (_label, _url, _icon, _name) in enumerate(STUDIO_ITEMS):
    _make_item(_label, _url, _icon, _name, _order * 10)


@hooks.register("insert_global_admin_css")
def studio_css():
    return format_html('<link rel="stylesheet" href="{}">', static("studio/studio.css"))
