from django.urls import include, path, reverse
from wagtail import hooks
from wagtail.admin.menu import Menu, MenuItem, SubmenuMenuItem

from . import urls as studio_urls

# Other studio features (briefs, runs, prompts) register their menu items on
# this hook, so the "Content Studio" submenu grows without editing this file.
studio_menu = Menu(
    register_hook_name="register_studio_menu_item",
    construct_hook_name="construct_studio_menu",
)


@hooks.register("register_admin_urls")
def register_studio_urls():
    return [path("studio/", include(studio_urls, namespace="studio"))]


@hooks.register("register_admin_menu_item")
def register_studio_menu():
    return SubmenuMenuItem(
        "Content Studio", studio_menu, icon_name="rocket", name="content-studio", order=150
    )


@hooks.register("register_studio_menu_item")
def register_overview_item():
    return MenuItem("Overview", reverse("studio:overview"), icon_name="home", name="studio-overview", order=0)
