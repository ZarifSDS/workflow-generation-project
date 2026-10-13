"""Starting audience profiles per region (B2B SaaS, EHS buyers). Edit them under Settings › Audience profiles."""

from django.db import migrations

COMMON_STYLE = (
    "B2B SaaS readers who are busy and practical: answer the question in the first sentence of each "
    "section, use plain words over jargon, keep paragraphs to 2-4 sentences, prefer numbered steps and short "
    "lists for procedures, and explain any acronym the first time. Speak to the reader as 'you'. No hype."
)
RANKING = (
    "Answer-first sections, a clear definition near the top, step-by-step how-to sections, a comparison "
    "table where readers weigh options, and an FAQ built from real 'People also ask' questions."
)

PROFILES = {
    "US": ("EHS managers, safety coordinators and operations leads at US companies that handle chemicals", "US spelling. Cite OSHA and the CFR."),
    "UK": ("Health and safety managers and compliance leads at UK organisations handling hazardous substances", "UK spelling. Cite HSE, COSHH and GB CLP."),
    "AU": ("WHS managers and safety advisers at Australian businesses", "Australian spelling. Cite Safe Work Australia and the model WHS Regulations."),
    "CA": ("Health and safety managers and JHSC members at Canadian employers", "Canadian spelling. Cite WHMIS, the HPR and provincial OHS rules."),
    "NZ": ("Health and safety managers at New Zealand businesses", "NZ spelling. Cite WorkSafe and the HSWA."),
    "EU": ("EHS and regulatory compliance managers at EU companies", "British-style English for an international reader. Cite REACH and CLP."),
}


def seed(apps, schema_editor):
    AudienceProfile = apps.get_model("studio", "AudienceProfile")
    for region, (audience, local) in PROFILES.items():
        AudienceProfile.objects.get_or_create(
            region=region,
            defaults={
                "audience": audience,
                "reading_grade": 8,
                "style": f"{COMMON_STYLE} {local}",
                "ranking_notes": RANKING,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("studio", "0007_audience_profiles")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
