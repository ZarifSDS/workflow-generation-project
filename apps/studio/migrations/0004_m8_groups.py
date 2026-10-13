"""Create the Content Studio role groups (docs/user-guide.md › Roles; apps/studio/permissions.py).

Writers and Operators are new; Editors and Moderators are Wagtail's own groups and keep their page
permissions. Adjust any of them later in Wagtail under Settings › Groups.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

GROUPS = {
    "Writers": [
        ("wagtailadmin", "access_admin"),
        ("studio", "access_studio"),
        ("studio", "review_writing_steps"),
        ("studio", "view_briefpreset"),
    ],
    "Editors": [
        ("wagtailadmin", "access_admin"),
        ("studio", "access_studio"),
        ("studio", "review_writing_steps"),
        ("studio", "review_editing_steps"),
        ("studio", "view_briefpreset"),
    ],
    "Moderators": [
        ("wagtailadmin", "access_admin"),
        ("studio", "access_studio"),
    ],
    "Operators": [
        ("wagtailadmin", "access_admin"),
        ("studio", "access_studio"),
        ("studio", "operate_studio"),
        ("studio", "add_briefpreset"),
        ("studio", "change_briefpreset"),
        ("studio", "delete_briefpreset"),
        ("studio", "view_briefpreset"),
    ],
}


def create_groups(apps, schema_editor):
    # Permissions are normally created after migrations; make sure the ones we assign exist now.
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None

    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    for name, perms in GROUPS.items():
        group, _ = Group.objects.get_or_create(name=name)
        for app_label, codename in perms:
            group.permissions.add(
                Permission.objects.get(content_type__app_label=app_label, codename=codename)
            )


class Migration(migrations.Migration):
    dependencies = [
        ("studio", "0003_m8_permissions"),
        ("wagtailadmin", "0001_create_admin_access_permissions"),
        ("wagtailcore", "0002_initial_data"),
    ]

    operations = [migrations.RunPython(create_groups, migrations.RunPython.noop)]
