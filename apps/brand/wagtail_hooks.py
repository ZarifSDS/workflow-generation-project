from django.templatetags.static import static
from django.utils.html import format_html
from wagtail import hooks


@hooks.register("insert_global_admin_css")
def theme_css():
    """The admin theme (palette, typography), loaded on every admin page including sign-in."""
    return format_html(
        '<link rel="preload" href="{}" as="font" type="font/ttf" crossorigin>'
        '<link rel="stylesheet" href="{}">',
        static("brand/fonts/Outfit-Variable.ttf"),
        static("brand/theme.css"),
    )
