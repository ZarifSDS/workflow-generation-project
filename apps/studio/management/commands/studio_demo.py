"""Fill the Content Studio with realistic example data so every screen can be reviewed.

All example content is labelled "[Example]" in the topic. Re-running replaces earlier examples.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.studio import services
from apps.studio.models import BriefPreset, ContentBrief, GenerationRun, MetadataOption, StepRun

EXAMPLE = "[Example] "

OUTLINE_V1 = """# SDS Retention Requirements: How Long to Keep Safety Data Sheets

## Search intent
EHS managers want the exact OSHA rule for keeping or discarding safety data sheets.

## Detailed outline

## What OSHA requires for SDS retention
- Answer first: SDSs count as employee exposure records under 29 CFR 1910.1020.
- You may discard an SDS if a record of the chemical's identity, where and when it was used is kept for 30 years. [VERIFY]

## How long to keep safety data sheets in practice
- Active chemicals: the current SDS must be readily accessible on every shift.
- Discontinued chemicals: compare keeping the SDS with keeping the 30-year identity record.

## Digital SDS records and audits
- What inspectors ask for and how a searchable SDS library shortens audits.
"""

OUTLINE_V2 = """# SDS Retention Requirements: How Long to Keep Safety Data Sheets

## Search intent
EHS managers at US manufacturing sites want the exact OSHA rule for keeping, archiving or discarding safety data sheets, and a practical retention policy.

## Detailed outline

## What OSHA requires for SDS retention
- Answer first in two sentences: under 29 CFR 1910.1020, SDSs are employee exposure records.
- An employer may discard an SDS if it keeps, for at least 30 years, a record of the chemical's identity, where it was used and when. [VERIFY]
- Distinguish the HazCom duty (current SDS accessible) from the records duty (30-year identity record).

## How long to keep safety data sheets in practice
- Active chemicals: keep the current SDS accessible on every shift, in every work area.
- Discontinued chemicals: keeping the SDS itself is the simplest way to meet the 30-year rule; the policy choices compared in a table.
- Superseded SDS revisions: keep or archive, and why many sites archive them.

## Building an SDS retention policy
- Who owns it, where records live, how archives are indexed, how often it is reviewed.

## Digital SDS records and audits
- What inspectors ask for; how a searchable SDS library and an archive of discontinued chemicals shorten audits.

## Claim verification table
| Claim | Source to verify | Confidence |
|---|---|---|
| SDSs are exposure records | 29 CFR 1910.1020(c)(5) | High |
| 30-year identity record allows discarding the SDS | 29 CFR 1910.1020(d)(1)(ii)(B) | Medium |
"""

RESEARCH = """## Key sources
- 29 CFR 1910.1200 (Hazard Communication): SDSs must be readily accessible during each work shift.
- 29 CFR 1910.1020 (Access to employee exposure and medical records): SDSs are exposure records; retention for the duration of employment plus 30 years, with the identity-record alternative. [VERIFY]

## Claims to carry into the outline
1. SDS retention is driven by the records standard, not HazCom alone.
2. The 30-year clock applies to the record of identity, use location and dates.
"""

LAB_RESEARCH = """## Key sources
- Model WHS Regulations, regulation 344-346: manufacturers and importers review SDSs at least every 5 years. [VERIFY]
- Register of hazardous chemicals: must list each chemical and include its current SDS.
"""


class Command(BaseCommand):
    help = "Create example briefs, presets and runs in different states for reviewing the Content Studio UI."

    @transaction.atomic
    def handle(self, *args, **options):
        user = get_user_model().objects.filter(is_superuser=True).first()
        ContentBrief.objects.filter(topic__startswith=EXAMPLE).delete()

        presets = [
            ("SDS Manager blog · US · FKGL 9", "seo_blog", "US", 9, 1800, "subtle"),
            ("SDS Manager blog · UK · FKGL 9", "seo_blog", "UK", 9, 1600, "subtle"),
            ("Guest post · UK · informational · FKGL 8", "outbound", "UK", 8, 1200, "none"),
            ("Lead magnet checklist · AU · FKGL 9", "lead_magnet", "AU", 9, 900, "button"),
        ]
        for name, content_type, region, fkgl, words, cta in presets:
            BriefPreset.objects.update_or_create(
                name=name,
                defaults={
                    "content_type": content_type,
                    "region": region,
                    "fkgl": fkgl,
                    "wordcount": words,
                    "cta_style": cta,
                    "narrative_mode": "informational" if content_type == "outbound" else "",
                    "audience": "EHS managers",
                    "comprehension": "practitioner",
                },
            )

        # 1. Needs review: outline ready, two versions plus the research step approved.
        b1 = ContentBrief.objects.create(
            topic=EXAMPLE + "How long to keep Safety Data Sheets",
            pkeyword="SDS retention requirements",
            skeywords=["how long to keep safety data sheets"],
            wordcount=1800,
            fkgl=9,
            region="US",
            audience="EHS managers at US manufacturing sites",
            content_type="seo_blog",
            created_by=user,
        )
        run1 = services.create_run(b1, {}, user)
        research = run1.steps.get(key="research")
        services.add_version(research, RESEARCH, provider="ollama_cloud", model="gpt-oss:120b")
        research.status = StepRun.Status.READY
        research.save()
        services.approve_step(research, user)
        outline = run1.steps.get(key="outline")
        services.add_version(outline, OUTLINE_V1, provider="ollama_cloud", model="gpt-oss:120b")
        services.add_version(
            outline, OUTLINE_V2, provider="ollama", model="huihui_ai/Qwen3.8-abliterated:latest"
        )
        outline.status = StepRun.Status.READY
        outline.provider, outline.model = "ollama", "huihui_ai/Qwen3.8-abliterated:latest"
        outline.save()
        services.refresh_run_status(run1)
        for kind, text, selected in [
            ("title", "SDS Retention Requirements: How Long to Keep SDSs", True),
            ("title", "How Long to Keep Safety Data Sheets Under OSHA", False),
            ("title", "SDS Retention Requirements Explained for EHS Teams", False),
            (
                "meta",
                "OSHA treats SDSs as exposure records. Learn the SDS retention requirements, the 30-year "
                "record rule, and what to keep when a chemical leaves your site.",
                True,
            ),
            (
                "meta",
                "How long to keep safety data sheets: the OSHA rules, the 30-year exception, and a simple "
                "retention policy for US manufacturing sites.",
                False,
            ),
            ("slug", "sds-retention-requirements", True),
        ]:
            MetadataOption.objects.create(run=run1, kind=kind, text=text, selected=selected)

        # 2. In progress: lead magnet with research approved and outline queued.
        b3 = ContentBrief.objects.create(
            topic=EXAMPLE + "SDS compliance checklist for small labs",
            pkeyword="SDS compliance checklist",
            skeywords=["chemical register"],
            wordcount=900,
            fkgl=9,
            region="AU",
            content_type="lead_magnet",
            audience="Lab managers at universities and small biotech labs",
            cta_style="button",
            created_by=user,
        )
        run3 = services.create_run(b3, {}, user)
        research3 = run3.steps.get(key="research")
        services.add_version(research3, LAB_RESEARCH, provider="ollama_cloud", model="gpt-oss:120b")
        research3.status = StepRun.Status.READY
        research3.save()
        services.approve_step(research3, user)

        # 3. Guest post waiting at the site crawl step (queued; runs once M4 connects generation).
        b2 = ContentBrief.objects.create(
            topic=EXAMPLE + "Secondary container labelling",
            pkeyword="secondary container labelling",
            skeywords=["workplace chemical labels", "GB CLP label requirements"],
            wordcount=1200,
            fkgl=8,
            region="UK",
            content_type="outbound",
            site="A UK warehouse operations blog",
            site_domain="https://example.com/",
            narrative_mode="informational",
            cta_style="none",
            audience="Warehouse supervisors and site H&S leads",
            created_by=user,
        )
        services.create_run(b2, {}, user)

        # 4. Rejected run, for the "recently finished" list.
        b4 = ContentBrief.objects.create(
            topic=EXAMPLE + "SDS authoring for importers",
            pkeyword="SDS authoring",
            wordcount=1500,
            fkgl=10,
            region="EU",
            content_type="seo_blog",
            created_by=user,
        )
        run4 = services.create_run(b4, {}, user)
        services.reject_run(run4, user, "Topic overlaps an existing article; merge instead.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Created 4 example briefs and runs ({GenerationRun.objects.filter(brief__topic__startswith=EXAMPLE).count()}"
                " runs) and 4 presets. Open /admin/studio/."
            )
        )
