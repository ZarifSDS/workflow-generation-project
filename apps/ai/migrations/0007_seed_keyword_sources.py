"""Seed the keyword data platforms the studio can read (Settings › Keyword data providers). They start
without keys, so nothing is asked until a key is entered; each row can be edited or deleted."""

from django.db import migrations

SOURCES = [
    ("semrush", "Semrush", "semrush", 10, "Batch keyword overview: volume, CPC, competition, difficulty, intent."),
    ("dataforseo", "DataForSEO", "dataforseo", 20, "Labs keyword overview: volume, CPC, difficulty, intent."),
    (
        "keywords_everywhere",
        "Keywords Everywhere",
        "keywords_everywhere",
        30,
        "Keyword data: volume, CPC, competition (no difficulty or intent).",
    ),
]


def seed(apps, schema_editor):
    KeywordSource = apps.get_model("ai", "KeywordSource")
    for name, label, platform, order, notes in SOURCES:
        KeywordSource.objects.get_or_create(
            name=name, defaults={"label": label, "platform": platform, "order": order, "notes": notes}
        )


def unseed(apps, schema_editor):
    apps.get_model("ai", "KeywordSource").objects.filter(
        name__in=[s[0] for s in SOURCES], api_key_encrypted=""
    ).delete()


class Migration(migrations.Migration):
    dependencies = [("ai", "0006_keyword_sources")]
    operations = [migrations.RunPython(seed, unseed)]
