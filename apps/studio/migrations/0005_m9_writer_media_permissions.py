"""M9 phase 5: writers add and choose images and documents from the editor.

Wagtail grants these per collection. Editors already have them (Wagtail's default group); writers get
add and choose on the root collection, so they can upload into the editor and pick existing files.
"""

from django.contrib.auth.management import create_permissions
from django.db import migrations

WRITER_MEDIA = [
    ("wagtailimages", "add_image"),
    ("wagtailimages", "choose_image"),
    ("wagtaildocs", "add_document"),
    ("wagtaildocs", "choose_document"),
]


def grant(apps, schema_editor):
    for app_config in apps.get_app_configs():
        app_config.models_module = True
        create_permissions(app_config, apps=apps, verbosity=0)
        app_config.models_module = None
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    Collection = apps.get_model("wagtailcore", "Collection")
    GroupCollectionPermission = apps.get_model("wagtailcore", "GroupCollectionPermission")
    writers = Group.objects.filter(name="Writers").first()
    root = Collection.objects.filter(depth=1).first()
    if writers is None or root is None:
        return
    for app_label, codename in WRITER_MEDIA:
        permission = Permission.objects.filter(content_type__app_label=app_label, codename=codename).first()
        if permission:
            GroupCollectionPermission.objects.get_or_create(
                group=writers, collection=root, permission=permission
            )


def revoke(apps, schema_editor):
    GroupCollectionPermission = apps.get_model("wagtailcore", "GroupCollectionPermission")
    GroupCollectionPermission.objects.filter(
        group__name="Writers",
        permission__codename__in=[codename for _, codename in WRITER_MEDIA],
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("studio", "0004_m8_groups"),
        ("wagtailcore", "0098_apitoken"),
        ("wagtailimages", "0027_image_description"),
        ("wagtaildocs", "0014_alter_document_file_size"),
    ]

    operations = [migrations.RunPython(grant, revoke)]
