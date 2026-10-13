from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ai.evaluation.report import summarise, to_markdown, write_into_doc


class Command(BaseCommand):
    help = "Combine a scored scorecard.md with results.json and write the table into docs/model-eval.md."

    def add_arguments(self, parser):
        parser.add_argument("run_dir")
        parser.add_argument(
            "--no-write", action="store_true", help="Print only; don't edit docs/model-eval.md"
        )

    def handle(self, *args, **opts):
        run_dir = Path(opts["run_dir"])
        if not (run_dir / "scorecard.md").exists():
            raise CommandError(f"No scorecard.md in {run_dir}")
        rows = summarise(run_dir)
        if not any(row["overall"] for row in rows):
            raise CommandError("The scorecard has no scores yet. Fill in scorecard.md first.")
        section = to_markdown(rows, f"Run {run_dir.name}")
        self.stdout.write(section)
        if not opts["no_write"]:
            write_into_doc(Path(settings.BASE_DIR) / "docs" / "model-eval.md", section)
            self.stdout.write(self.style.SUCCESS("Written to docs/model-eval.md"))
