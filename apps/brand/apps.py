from django.apps import AppConfig


class BrandConfig(AppConfig):
    """The admin's look: palette and typography over Wagtail's own tokens (no rebranding)."""

    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.brand"
    label = "brand"
    verbose_name = "Admin theme"
