"""Render a branded infographic from a JSON spec (apps/quality/infographic.py).

    python manage.py render_infographic steps spec.json out/            # your spec
    python manage.py render_infographic steps --example out/            # the template's example spec

Writes <slug>.svg, <slug>.png (1600 px wide) and <slug>.webp (1200 px) and prints the alt text and the checks.
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from apps.quality import infographic
from apps.quality.infographic_examples import EXAMPLES


class Command(BaseCommand):
    help = "Render a branded infographic (steps, decision, columns, part_to_whole, bars, form_anatomy)."

    def add_arguments(self, parser):
        parser.add_argument("kind", choices=list(infographic.TEMPLATES))
        parser.add_argument("spec", nargs="?", help="JSON file with the spec")
        parser.add_argument("out", nargs="?", default=".", help="folder to write the files to")
        parser.add_argument("--example", action="store_true", help="use the template's example spec")

    def handle(self, kind, spec=None, out=".", example=False, **options):
        if example:
            out = spec or out
            data = EXAMPLES[kind]
        elif spec:
            data = json.loads(Path(spec).read_text(encoding="utf-8"))
        else:
            raise CommandError("Give a spec file, or --example.")
        result = infographic.render(kind, data)
        for problem in result.problems:
            self.stdout.write(f"[{problem['level']}] {problem['text']}")
        if result.blocked:
            raise CommandError("Not drawn: fix the problems above.")
        folder = Path(out)
        folder.mkdir(parents=True, exist_ok=True)
        stem = slugify(data["title"].replace("**", ""))[:80] or kind
        (folder / f"{stem}.svg").write_text(result.svg, encoding="utf-8")
        (folder / f"{stem}.png").write_bytes(result.png)
        (folder / f"{stem}.webp").write_bytes(result.webp)
        self.stdout.write(
            self.style.SUCCESS(f"Wrote {folder / stem}.svg, .png and .webp ({result.width}x{result.height})")
        )
        self.stdout.write(f"Alt text: {result.alt}")
