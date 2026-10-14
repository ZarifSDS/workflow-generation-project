from pathlib import Path

from django.core.management.base import BaseCommand

from apps.studio import replay
from apps.studio.models import StepVersion


class Command(BaseCommand):
    help = "Replay the SOP's deterministic checks over stored step versions (no model calls)."

    def add_arguments(self, parser):
        parser.add_argument("--runs", nargs="*", type=int, help="Run ids (default: every run).")
        parser.add_argument("--steps", nargs="*", help="Step keys, e.g. draft review_edit.")
        parser.add_argument("--latest", action="store_true", help="Only each step's latest version.")
        parser.add_argument("--out", help="Write the Markdown report to this file instead of stdout.")

    def handle(self, *args, **options):
        versions = StepVersion.objects.select_related("step__run__brief").order_by("step__run_id", "pk")
        if options["runs"]:
            versions = versions.filter(step__run_id__in=options["runs"])
        if options["steps"]:
            versions = versions.filter(step__key__in=options["steps"])
        if options["latest"]:
            latest = {}
            for version in versions:
                latest[version.step_id] = version
            versions = list(latest.values())
        report = replay.to_markdown(replay.replay_versions(versions))
        if options["out"]:
            Path(options["out"]).parent.mkdir(parents=True, exist_ok=True)
            Path(options["out"]).write_text(report, encoding="utf-8")
            self.stdout.write(f"Wrote {options['out']}")
        else:
            self.stdout.write(report)
