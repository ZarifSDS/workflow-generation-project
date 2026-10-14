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
from .models import AudienceProfile, BriefPreset, GenerationRun, StepRun
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


class AudienceProfileViewSet(ModelViewSet):
    """Settings › Audience profiles: who we write for per region; feeds every prompt and the chat."""

    model = AudienceProfile
    icon = "group"
    menu_label = "Audience profiles"
    add_to_settings_menu = True
    menu_order = 902
    url_prefix = "studio/audiences"
    url_namespace = "studio_audiences"
    list_display = ["region", "audience", "reading_grade"]
    form_fields = ["region", "audience", "reading_grade", "style", "ranking_notes"]


@hooks.register("register_admin_viewset")
def register_preset_viewset():
    return [preset_viewset, AudienceProfileViewSet("studio_audiences")]


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
    ("Image generator", "studio:images", "image", "studio-images", permissions.ACCESS),
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


class SuperuserMenuItem(MenuItem):
    def is_shown(self, request):
        return request.user.is_superuser


@hooks.register("register_settings_menu_item")
def register_provider_keys_menu():
    """Settings › AI providers: API keys and added providers (ADR 0008). Superusers only."""
    return SuperuserMenuItem(
        "AI providers", reverse("studio:provider_keys"), icon_name="key", name="ai-providers", order=900
    )


@hooks.register("register_settings_menu_item")
def register_task_defaults_menu():
    """Settings › Default models: the default model and fallback per task. Superusers only."""
    return SuperuserMenuItem(
        "Default models", reverse("studio:task_defaults"), icon_name="cogs", name="ai-defaults", order=901
    )


@hooks.register("register_settings_menu_item")
def register_search_providers_menu():
    """Settings › Search data providers: keys for the Search results step. Superusers only."""
    return SuperuserMenuItem(
        "Search data providers",
        reverse("studio:search_providers"),
        icon_name="search",
        name="search-providers",
        order=903,
    )


@hooks.register("register_log_actions")
def register_ai_log_actions(actions):
    """History entries for provider settings. They never contain a key, only its last characters."""

    def changed(log_entry):
        parts = (log_entry.data or {}).get("changed") or []
        return f"Set {', '.join(parts)}" if parts else "Set API key"

    actions.register_action("ai.key_set", "Set API key", changed)
    actions.register_action("ai.key_removed", "Remove API key", "Removed the stored API key")
    actions.register_action("ai.provider_added", "Add AI provider", "Added the provider")
    actions.register_action("ai.provider_changed", "Change AI provider", "Changed the provider")
    actions.register_action("ai.provider_deleted", "Delete AI provider", "Deleted the provider")
    actions.register_action("ai.model_added", "Add AI model", "Added the model")
    actions.register_action("ai.model_removed", "Remove AI model", "Removed the model")

    def default_set(data):
        return f"{data.get('task')}: {data.get('model')}, fallback {data.get('fallback')}"

    actions.register_action("ai.default_set", "Set default model", default_set)
    actions.register_action("ai.default_reset", "Reset default model", "Back to the built-in model")


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
