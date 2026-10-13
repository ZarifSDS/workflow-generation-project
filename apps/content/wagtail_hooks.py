"""Rich text features for article pages that Wagtail 8 doesn't fully provide.

- underline: a new Draftail inline style stored as <u> (the dialect's ++text++).
- Sanitiser rules ("editorhtml") for underline, strikethrough, code and blockquote: Wagtail registers
  the editor side of the last three but not the rules its DB-HTML sanitiser
  (APIRichText.sanitize_db_html) uses, so publishing would otherwise strip them.
"""

import wagtail.admin.rich_text.editors.draftail.features as draftail_features
from wagtail import hooks
from wagtail.admin.rich_text.converters.editor_html import WhitelistRule
from wagtail.admin.rich_text.converters.html_to_contentstate import InlineStyleElementHandler
from wagtail.whitelist import allow_without_attributes


@hooks.register("register_rich_text_features")
def register_underline(features):
    features.register_editor_plugin(
        "draftail",
        "underline",
        draftail_features.InlineStyleFeature({"type": "UNDERLINE", "label": "U", "description": "Underline"}),
    )
    features.register_converter_rule(
        "contentstate",
        "underline",
        {
            "from_database_format": {"u": InlineStyleElementHandler("UNDERLINE")},
            "to_database_format": {"style_map": {"UNDERLINE": "u"}},
        },
    )


@hooks.register("register_rich_text_features")
def register_sanitiser_rules(features):
    for feature, elements in {
        "underline": ["u"],
        "strikethrough": ["s"],
        "code": ["code"],
        "blockquote": ["blockquote"],
    }.items():
        features.register_converter_rule(
            "editorhtml", feature, [WhitelistRule(element, allow_without_attributes) for element in elements]
        )
