"""Blind model evaluation: same brief and prompt, many candidates, shuffled labels.

Layout of a run directory:
    outputs/<brief>/<label>.md   model output (no model name inside)
    images/<brief>/<label>.<ext> image round outputs
    key.json                     label -> provider/model (open only after scoring)
    results.json                 per job: status, timing, metrics
    scorecard.md                 blank rubric for the human scorer
"""

import json
import random
import string
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import yaml

from ..types import ProviderError
from . import metrics

ROUNDS = ("outline", "draft", "image")
RUBRIC = ["Accuracy", "Structure", "Voice", "Search fit", "Edit effort"]


def load_yaml(path):
    with open(path, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def render_messages(template_path, brief, types, outline=None):
    """Fill a prompt template (sections '## system' and '## user') with brief fields."""
    template = Path(template_path).read_text(encoding="utf-8")
    type_config = types[brief["type"]]
    extra_rows = []
    if brief.get("site"):
        extra_rows.append(f"| Target site | {brief['site']} |")
    if brief.get("narrative_mode"):
        extra_rows.append(f"| Narrative mode | {brief['narrative_mode']} |")
    if brief.get("cta_style"):
        extra_rows.append(f"| CTA style | {brief['cta_style']} |")
    values = {
        "type_label": type_config["label"],
        "type_instructions": type_config["instructions"].strip(),
        "topic": brief["topic"],
        "pkeyword": brief["pkeyword"],
        "skeywords": ", ".join(brief.get("skeywords", [])) or "none",
        "wordcount": brief.get("wordcount", ""),
        "fkgl": brief.get("fkgl", ""),
        "audience": brief.get("audience", ""),
        "comprehension": brief.get("comprehension", "practitioner"),
        "region": brief.get("region", "US"),
        "notes": " ".join(str(brief.get("notes", "")).split()),
        "extra_rows": "\n".join(extra_rows),
        "outline": outline or "",
    }
    for key, value in values.items():
        template = template.replace("{{" + key + "}}", str(value))
    system, _, user = template.partition("## user")
    return [
        {"role": "system", "content": system.replace("## system", "", 1).strip()},
        {"role": "user", "content": user.strip()},
    ]


def assign_labels(brief_ids, candidates, seed):
    """Per brief, shuffle candidates and give them letters, so labels don't reveal models."""
    rng = random.Random(seed)
    key = {}
    for brief_id in brief_ids:
        order = list(range(len(candidates)))
        rng.shuffle(order)
        key[brief_id] = {string.ascii_uppercase[pos]: candidates[idx] for pos, idx in enumerate(order)}
    return key


def write_scorecard(path, key, round_name):
    lines = [
        f"# Scorecard: {round_name} round",
        "",
        "Score each output 1–5 per criterion (5 = best). Don't open key.json until you're done.",
        "",
        "- **Accuracy:** no invented rules, figures or sources; correct region and law",
        "- **Structure:** follows the brief/outline; logical flow",
        "- **Voice:** plain, expert B2B tone; no filler or AI tells",
        "- **Search fit:** answers the search intent; keywords used naturally",
        "- **Edit effort:** how little work it needs before publishing (5 = minimal)",
        "",
    ]
    for brief_id, labels in key.items():
        lines += [f"## {brief_id}", "", "| Label | " + " | ".join(RUBRIC) + " | Notes |"]
        lines.append("|---" * (len(RUBRIC) + 2) + "|")
        lines += [f"| {label} |" + "  |" * len(RUBRIC) + "  |" for label in sorted(labels)]
        lines.append("")
    Path(path).write_text("\n".join(lines), encoding="utf-8")


class Runner:
    def __init__(
        self,
        run_dir,
        round_name,
        briefs,
        candidates,
        types,
        prompts_dir,
        generate,
        generate_image,
        outlines=None,
        log=print,
        seed=None,
    ):
        self.run_dir = Path(run_dir)
        self.round = round_name
        self.briefs = {brief["id"]: brief for brief in briefs}
        self.candidates = candidates
        self.types = types
        self.prompts_dir = Path(prompts_dir)
        self.generate = generate
        self.generate_image = generate_image
        self.outlines = outlines or {}
        self.log = log
        self.seed = seed if seed is not None else int(time.time())
        self._lock = threading.Lock()
        self.results = {}

    def _load_or_create_key(self):
        key_path = self.run_dir / "key.json"
        if key_path.exists():
            return json.loads(key_path.read_text(encoding="utf-8"))
        key = assign_labels(list(self.briefs), self.candidates, self.seed)
        key_path.write_text(json.dumps(key, indent=2), encoding="utf-8")
        return key

    def _save_results(self):
        path = self.run_dir / "results.json"
        path.write_text(json.dumps(self.results, indent=2, default=str), encoding="utf-8")

    def _job(self, brief_id, label, candidate):
        brief = self.briefs[brief_id]
        record = {"provider": candidate["provider"], "model": candidate["model"], "status": "pending"}
        try:
            if self.round == "image":
                image = self.generate_image(
                    candidate["provider"],
                    candidate["model"],
                    " ".join(brief["hero_prompt"].split()),
                    candidate.get("options", {}),
                )
                ext = image.mime_type.split("/")[-1].replace("jpeg", "jpg")
                path = self.run_dir / "images" / brief_id / f"{label}.{ext}"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(image.data)
                record.update(
                    status="ok",
                    file=str(path.relative_to(self.run_dir)),
                    total_time=image.total_time,
                    attempts=image.attempts,
                )
            else:
                template = self.prompts_dir / f"{self.round}.md"
                messages = render_messages(template, brief, self.types, self.outlines.get(brief_id))
                options = {"temperature": 0.6, "max_tokens": 16000, **candidate.get("options", {})}
                result = self.generate(candidate["provider"], candidate["model"], messages, options)
                path = self.run_dir / "outputs" / brief_id / f"{label}.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(result.text, encoding="utf-8")
                record.update(
                    status="ok" if result.text.strip() else "empty",
                    file=str(path.relative_to(self.run_dir)),
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    time_to_first_token=result.time_to_first_token,
                    total_time=result.total_time,
                    tokens_per_second=result.tokens_per_second,
                    attempts=result.attempts,
                    stats=result.stats,
                    metrics=metrics.compute(result.text, brief),
                )
        except ProviderError as error:
            record.update(status="failed", error_kind=error.kind, error=str(error)[:500])
        except Exception as error:  # noqa: BLE001 - one bad candidate must not stop the run
            record.update(status="failed", error_kind="unexpected", error=repr(error)[:500])
        with self._lock:
            self.results.setdefault(brief_id, {})[label] = record
            self._save_results()
        self.log(f"[{record['status']:6}] {brief_id} {label} ({record.get('total_time') or 0:.0f}s)")

    def run(self, workers_per_provider=1):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        key = self._load_or_create_key()
        results_path = self.run_dir / "results.json"
        if results_path.exists():
            self.results = json.loads(results_path.read_text(encoding="utf-8"))
        if not (self.run_dir / "scorecard.md").exists():
            write_scorecard(self.run_dir / "scorecard.md", key, self.round)

        # Group jobs by provider: providers run in parallel, each provider's jobs run in order.
        # Local Ollama must stay sequential (one model in memory at a time).
        groups = defaultdict(list)
        for brief_id, labels in key.items():
            if self.round == "draft" and brief_id not in self.outlines:
                self.log(f"[skip  ] {brief_id}: no approved outline in eval/outlines/{brief_id}.md")
                continue
            for label, candidate in sorted(labels.items()):
                if self.results.get(brief_id, {}).get(label, {}).get("status") == "ok":
                    continue  # resume: already done
                groups[candidate["provider"]].append((brief_id, label, candidate))
        # Run each model's jobs together so a local model loads once.
        for jobs in groups.values():
            jobs.sort(key=lambda job: (job[2]["model"], job[0]))

        def run_group(jobs):
            for job in jobs:
                self._job(*job)

        if groups:
            with ThreadPoolExecutor(max_workers=len(groups) * workers_per_provider) as pool:
                list(pool.map(run_group, groups.values()))
        return self.results
