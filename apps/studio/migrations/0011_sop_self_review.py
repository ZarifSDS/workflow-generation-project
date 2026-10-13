from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("studio", "0010_metadata_tags_excerpt"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentbrief",
            name="anchors",
            field=models.JSONField(
                blank=True,
                default=list,
                help_text=(
                    "Guest posts: [{text, url}] pairs from the brief sheet, in order; each URL a different "
                    "product page."
                ),
                verbose_name="Anchors",
            ),
        ),
        migrations.AddField(
            model_name="contentbrief",
            name="source_reference",
            field=models.CharField(
                blank=True,
                help_text="Where the brief came from, e.g. Guest Post Plan sheet, row 14.",
                max_length=120,
                verbose_name="Brief source",
            ),
        ),
        migrations.AddField(
            model_name="generationrun",
            name="autopilot",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Started in autopilot: steps self-review against the SOP and only hold where they can't pass."
                ),
            ),
        ),
        migrations.AddField(
            model_name="steprun",
            name="self_review",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "The SOP reviewer checks the output and the model revises it until it passes "
                    "(apps/studio/sop.py)."
                ),
                verbose_name="SOP self-review",
            ),
        ),
    ]
