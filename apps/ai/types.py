from dataclasses import dataclass, field


class ProviderError(Exception):
    """A provider call failed. `kind` lets callers decide whether to retry or fall back."""

    # kinds: "not_configured", "not_free", "unavailable", "rate_limited", "server", "network",
    # "bad_request", "auth", "unknown"
    RETRYABLE = {"rate_limited", "server", "network"}

    def __init__(self, kind, message, status=None):
        super().__init__(message)
        self.kind = kind
        self.status = status

    @property
    def retryable(self):
        return self.kind in self.RETRYABLE


@dataclass
class GenerationResult:
    provider: str
    model: str
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    time_to_first_token: float | None = None  # seconds
    total_time: float | None = None  # seconds
    tokens_per_second: float | None = None
    attempts: int = 1
    stats: dict = field(default_factory=dict)  # provider-specific extras (e.g. Ollama GPU/CPU split)


@dataclass
class ImageResult:
    provider: str
    model: str
    data: bytes
    mime_type: str
    total_time: float | None = None
    attempts: int = 1
    stats: dict = field(default_factory=dict)
