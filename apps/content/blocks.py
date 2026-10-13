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
    "h2",
    "h3",
    "ol",
    "ul",
    "h4",
    "code",
    "blockquote",
    "hr",
    "image",
    "embed",
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
    """The company CMS's "Custom image" (image, width, height), plus a caption."""

    image = ImageBlock()
    caption = blocks.CharBlock(required=False, max_length=255)
    width = blocks.IntegerBlock(
        required=False, min_value=1, help_text="Set the image width in pixels (optional)"
    )
    height = blocks.IntegerBlock(
        required=False, min_value=1, help_text="Set the image height in pixels (optional)"
    )

    class Meta:
        icon = "image"
        label = "Custom image"
        template = "content/blocks/figure.html"


class FAQItemBlock(blocks.StructBlock):
    question = blocks.CharBlock(max_length=255, help_text="The question")
    answer = blocks.RichTextBlock(features=RICH_TEXT_FEATURES, help_text="The answer (supports rich text)")

    class Meta:
        label = "FAQ item"


class FAQBlock(blocks.StructBlock):
    title = blocks.CharBlock(required=False, max_length=255, help_text="section title")
    items = blocks.ListBlock(FAQItemBlock(), help_text="List of Q&A items")

    class Meta:
        icon = "help"
        label = "FAQ"
        template = "content/blocks/faq.html"


# Labels follow the company CMS (Custom richtext, Table, Custom image, FAQ); Heading and Embed are ours:
# they keep #anchors and video embeds as their own blocks, so the Markdown dialect maps onto them.
ARTICLE_BLOCKS = [
    ("heading", HeadingBlock()),
    ("paragraph", blocks.RichTextBlock(features=RICH_TEXT_FEATURES, label="Custom richtext", icon="pilcrow")),
    ("figure", FigureBlock()),
    ("embed", EmbedBlock(icon="media")),
    ("table", TableBlock(label="Table")),
    ("faq", FAQBlock()),
]


class AgendaItemBlock(blocks.StructBlock):
    time = blocks.CharBlock(required=False, max_length=20, help_text="Time offset, e.g. 0:00 or 9:12")
    title = blocks.CharBlock(max_length=255, help_text="Agenda item title")
    description = blocks.CharBlock(
        required=False, max_length=255, help_text="Short sub-line shown under the title"
    )

    class Meta:
        icon = "time"
        label = "Agenda item"
