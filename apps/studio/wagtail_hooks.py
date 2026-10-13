import copy

from django.contrib.auth.models import Permission
from django.templatetags.static import static
from django.urls import include, path, reverse
from django.utils.html import format_html
from wagtail import hooks
from wagtail.admin.menu import Menu, MenuItem, SubmenuMenuItem
from wagtail.admin.ui.components import Component
from wagtail.admin.viewsets.model import ModelViewSet

from . import permissions
from . import urls as studio_urls
from .models import BriefPreset, GenerationRun, StepRun
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


class StudioSubmenuItem(SubmenuMenuItem):
    def is_shown(self, request):
        return request.user.has_perm(permissions.ACCESS) and super().is_shown(request)


class PermissionMenuItem(MenuItem):
    """A Content Studio menu entry shown only to users with `permission`."""

    def __init__(self, *args, permission=permissions.ACCESS, **kwargs):
        super().__init__(*args, **kwargs)
        self.permission = permission

    def is_shown(self, request):
        return request.user.has_perm(self.permission)


@hooks.register("register_admin_menu_item")
def register_studio_menu():
    return StudioSubmenuItem(
        "Content Studio", studio_menu, icon_name="draft", name="content-studio", order=150
    )


@hooks.register("register_permissions")
def register_studio_permissions():
    """List the Content Studio permissions in Settings › Groups."""
    codenames = [codename for codename, _ in permissions.PERMISSIONS]
    return Permission.objects.filter(content_type__app_label="studio", codename__in=codenames)


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
    ("Dashboard", "studio:dashboard", "home", "studio-dashboard", permissions.ACCESS),
    ("New brief", "studio:brief_new", "plus", "studio-new-brief", permissions.WRITING),
    ("Briefs", "studio:briefs", "doc-full", "studio-briefs", permissions.ACCESS),
    ("Runs", "studio:runs", "list-ul", "studio-runs", permissions.ACCESS),
    ("Presets", "studio_presets:index", "form", "studio-presets", "studio.view_briefpreset"),
    ("Models and providers", "studio:providers", "cogs", "studio-providers", permissions.ACCESS),
]


def _make_item(label, url_name, icon, name, order, permission):
    @hooks.register("register_studio_menu_item")
    def register():
        return PermissionMenuItem(
            label, reverse(url_name), icon_name=icon, name=name, order=order, permission=permission
        )

    return register


for _order, (_label, _url, _icon, _name, _permission) in enumerate(STUDIO_ITEMS):
    _make_item(_label, _url, _icon, _name, _order * 10, _permission)


@hooks.register("insert_global_admin_css")
def studio_css():
    return format_html('<link rel="stylesheet" href="{}">', static("studio/studio.css"))


class StudioReviewPanel(Component):
    """Dashboard: steps the signed-in user can approve now."""

    name = "studio_review"
    order = 50
    template_name = "studio/home/review_panel.html"

    def get_context_data(self, parent_context):
        user = parent_context["request"].user
        ready = StepRun.objects.filter(
            status=StepRun.Status.READY, run__status=GenerationRun.Status.NEEDS_REVIEW
        ).select_related("run__brief")
        steps = [step for step in ready.order_by("finished_at")[:50] if permissions.can_review(user, step)]
        return {"steps": steps[:8]}


class StudioRecentRunsPanel(Component):
    name = "studio_recent_runs"
    order = 60
    template_name = "studio/home/recent_runs_panel.html"

    def get_context_data(self, parent_context):
        return {"runs": GenerationRun.objects.select_related("brief").order_by("-updated_at")[:6]}


@hooks.register("construct_homepage_panels")
def studio_dashboard_panels(request, panels):
    """Content Studio's own panels replace Wagtail's release notes for studio users."""
    panels[:] = [panel for panel in panels if getattr(panel, "name", "") != "whats_new_in_wagtail_version"]
    if request.user.has_perm(permissions.ACCESS):
        panels.extend([StudioReviewPanel(), StudioRecentRunsPanel()])
