"""StreamField blocks for ArticlePage. Each one matches a construct of the Markdown dialect (ADR 0007),
so a reviewed draft maps onto the page without losing anything."""

from wagtail import blocks
from wagtail.contrib.table_block.blocks import TableBlock
from wagtail.embeds.blocks import EmbedBlock
from wagtail.images.blocks import ImageBlock

RICH_TEXT_FEATURES = [
    "bold",
    "italic",
    "underline",
    "strikethrough",
    "link",
    "document-link",
    "ol",
    "ul",
    "h4",
    "code",
    "blockquote",
    "hr",
]


class HeadingBlock(blocks.StructBlock):
    text = blocks.CharBlock(max_length=255)
    level = blocks.ChoiceBlock(choices=[("h2", "Section (H2)"), ("h3", "Subsection (H3)")], default="h2")
    anchor = blocks.CharBlock(
        required=False,
        max_length=80,
        help_text="Link target for #anchor links, e.g. what-counts. Filled from the draft.",
    )

    class Meta:
        icon = "title"
        template = "content/blocks/heading.html"


class FigureBlock(blocks.StructBlock):
    image = ImageBlock()
    caption = blocks.CharBlock(required=False, max_length=255)

    class Meta:
        icon = "image"
        label = "Image"
        template = "content/blocks/figure.html"


class FAQItemBlock(blocks.StructBlock):
    question = blocks.CharBlock(max_length=255)
    answer = blocks.RichTextBlock(features=RICH_TEXT_FEATURES)


class FAQBlock(blocks.StructBlock):
    items = blocks.ListBlock(FAQItemBlock())

    class Meta:
        icon = "help"
        label = "FAQ"
        template = "content/blocks/faq.html"


ARTICLE_BLOCKS = [
    ("heading", HeadingBlock()),
    ("paragraph", blocks.RichTextBlock(features=RICH_TEXT_FEATURES)),
    ("figure", FigureBlock()),
    ("embed", EmbedBlock(icon="media")),
    ("table", TableBlock()),
    ("faq", FAQBlock()),
]
