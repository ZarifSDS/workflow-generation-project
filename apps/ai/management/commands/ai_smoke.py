from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from apps.ai.providers import get_providers
from apps.ai.service import generate, generate_image
from apps.ai.types import ProviderError

TEXT_CHECKS = {
    "ollama": "gemma4:e4b",
    "ollama_cloud": "gpt-oss:20b",
    "gemini": "gemini-3.7-flash",
    "groq": "openai/gpt-oss-20b",
}
IMAGE_CHECKS = ["@cf/black-forest-labs/flux-1-schnell", "@cf/black-forest-labs/flux-2-klein-4b"]


class Command(BaseCommand):
    help = "One tiny call per configured provider to confirm keys, endpoints and adapters work."

    def add_arguments(self, parser):
        parser.add_argument("--no-images", action="store_true", help="Skip Cloudflare image checks")

    def handle(self, *args, **options):
        providers = get_providers()
        messages = [{"role": "user", "content": "Reply with exactly: OK"}]
        for name, model in TEXT_CHECKS.items():
            if not providers[name].is_configured:
                self.stdout.write(f"{name:13} skipped (not configured)")
                continue
            try:
                result = generate(name, model, messages, {"max_tokens": 200, "temperature": 0}, retries=0)
                speed = f"{result.tokens_per_second:.1f} tok/s" if result.tokens_per_second else "n/a tok/s"
                self.stdout.write(f"{name:13} OK   {model}: {result.text.strip()[:40]!r} ({speed})")
            except ProviderError as error:
                self.stdout.write(self.style.ERROR(f"{name:13} FAIL {model}: [{error.kind}] {error}"))

        if options["no_images"] or not providers["cloudflare"].is_configured:
            return
        out_dir = Path(settings.MEDIA_ROOT) / "smoke"
        out_dir.mkdir(parents=True, exist_ok=True)
        for model in IMAGE_CHECKS:
            try:
                image = generate_image(
                    "cloudflare",
                    model,
                    "A clean, well-lit chemical storage room with labelled bottles",
                    {"width": 512, "height": 512, "steps": 4},
                    retries=0,
                )
                path = out_dir / f"{model.rsplit('/', 1)[-1]}.{image.mime_type.split('/')[-1]}"
                path.write_bytes(image.data)
                self.stdout.write(
                    f"cloudflare    OK   {model}: {len(image.data) // 1024} KB {image.mime_type} -> {path}"
                )
            except ProviderError as error:
                self.stdout.write(self.style.ERROR(f"cloudflare    FAIL {model}: [{error.kind}] {error}"))
