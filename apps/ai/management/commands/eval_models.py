import time
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.ai.evaluation.runner import ROUNDS, Runner, load_yaml
from apps.ai.service import generate, generate_image
from apps.ai.types import GenerationResult, ImageResult

EVAL_DIR = Path(settings.BASE_DIR) / "eval"

FAKE_MARKDOWN = (
    "# SDS retention requirements explained\n\nSDS retention requirements depend on exposure records. "
    "Employers keep a record of each chemical for 30 years under 29 CFR 1910.1020.\n\n"
    "## Who must keep records\n\nEmployers with hazardous chemicals must keep records [VERIFY].\n"
)


def fake_generate(provider, model, messages, options):
    return GenerationResult(
        provider=provider, model=model, text=FAKE_MARKDOWN, output_tokens=60, total_time=0.01
    )


def fake_generate_image(provider, model, prompt, options):
    return ImageResult(
        provider=provider, model=model, data=b"\x89PNG fake", mime_type="image/png", total_time=0.01
    )


class Command(BaseCommand):
    help = "Run a blind model-evaluation round (outline, draft or image) over the eval briefs."

    def add_arguments(self, parser):
        parser.add_argument("--round", choices=ROUNDS, required=True)
        parser.add_argument("--run-dir", help="Resume or extend an existing run directory")
        parser.add_argument("--briefs", default=str(EVAL_DIR / "briefs.yaml"))
        parser.add_argument("--candidates", default=str(EVAL_DIR / "candidates.yaml"))
        parser.add_argument("--only-briefs", help="Comma-separated brief ids to include")
        parser.add_argument("--models", help="Comma-separated substrings; only matching models run")
        parser.add_argument(
            "--outlines-dir",
            default=str(EVAL_DIR / "outlines"),
            help="Draft round: approved outlines as <brief-id>.md",
        )
        parser.add_argument("--seed", type=int)
        parser.add_argument("--dry-run", action="store_true", help="Use fake providers (no API calls)")

    def handle(self, *args, **opts):
        briefs = load_yaml(opts["briefs"])
        if opts["only_briefs"]:
            wanted = {item.strip() for item in opts["only_briefs"].split(",")}
            briefs = [brief for brief in briefs if brief["id"] in wanted]
        kind = "image" if opts["round"] == "image" else "text"
        candidates = load_yaml(opts["candidates"])[kind]
        if opts["models"]:
            needles = [needle.strip() for needle in opts["models"].split(",")]
            candidates = [c for c in candidates if any(needle in c["model"] for needle in needles)]
        if not briefs or not candidates:
            raise CommandError("No briefs or candidates selected.")

        outlines = {}
        if opts["round"] == "draft":
            for brief in briefs:
                path = Path(opts["outlines_dir"]) / f"{brief['id']}.md"
                if path.exists():
                    outlines[brief["id"]] = path.read_text(encoding="utf-8")

        run_dir = (
            Path(opts["run_dir"])
            if opts["run_dir"]
            else (EVAL_DIR / "runs" / f"{time.strftime('%Y%m%d-%H%M')}-{opts['round']}")
        )
        runner = Runner(
            run_dir=run_dir,
            round_name=opts["round"],
            briefs=briefs,
            candidates=candidates,
            types=load_yaml(EVAL_DIR / "prompts" / "types.yaml"),
            prompts_dir=EVAL_DIR / "prompts",
            generate=fake_generate if opts["dry_run"] else generate,
            generate_image=fake_generate_image if opts["dry_run"] else generate_image,
            outlines=outlines,
            log=lambda line: self.stdout.write(line),
            seed=opts["seed"],
        )
        self.stdout.write(f"Run directory: {run_dir}")
        self.stdout.write(f"{len(briefs)} brief(s) x {len(candidates)} candidate(s), round '{opts['round']}'")
        results = runner.run()
        done = sum(1 for labels in results.values() for r in labels.values() if r["status"] == "ok")
        failed = [
            f"{brief_id}/{label} {r['model']}: {r.get('error_kind')}"
            for brief_id, labels in results.items()
            for label, r in labels.items()
            if r["status"] != "ok"
        ]
        self.stdout.write(self.style.SUCCESS(f"Finished: {done} ok, {len(failed)} not ok"))
        for line in failed:
            self.stdout.write(self.style.WARNING(f"  {line}"))
        self.stdout.write(
            f"Score {run_dir / 'scorecard.md'}, then run: python manage.py eval_report {run_dir}"
        )
