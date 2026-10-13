"""Provider availability checks, shared by the `ai_smoke` command and the Models and providers screen."""

from .models import ProviderCheck
from .providers import get_providers
from .service import generate
from .types import ProviderError

TEXT_CHECKS = {
    "ollama": "gemma4:e4b",
    "ollama_cloud": "gpt-oss:20b",
    "gemini": "gemini-3.7-flash",
    "groq": "openai/gpt-oss-20b",
}
MESSAGES = [{"role": "user", "content": "Reply with exactly: OK"}]


def check_text_providers(save=True):
    """One tiny call per text provider. Returns {provider: (ok, detail)}."""
    providers = get_providers()
    results = {}
    for name, model in TEXT_CHECKS.items():
        spec = providers.get(name)
        if spec is None or not spec.is_configured:
            results[name] = (False, "Not configured: add its key to .env")
            continue
        try:
            generate(name, model, MESSAGES, {"max_tokens": 200, "temperature": 0}, retries=0)
            results[name] = (True, f"Responded ({model})")
        except ProviderError as error:
            results[name] = (False, f"{error.kind}: {str(error)[:200]}")
    cloudflare = providers.get("cloudflare")
    if cloudflare is not None:
        results["cloudflare"] = (
            (True, "Key and account configured (image calls not made by the check)")
            if cloudflare.is_configured
            else (False, "Not configured: add the account ID and token to .env")
        )
    if save:
        for name, (ok, detail) in results.items():
            ProviderCheck.objects.update_or_create(provider=name, defaults={"ok": ok, "detail": detail})
    return results
