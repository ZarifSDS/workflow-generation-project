from django.conf import settings
from django.db import models


class ProviderCheck(models.Model):
    """Result of the last availability check per provider, shown on the Models and providers screen."""

    provider = models.CharField(max_length=30, unique=True)
    ok = models.BooleanField(default=False)
    detail = models.CharField(max_length=500, blank=True)
    checked_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.provider}: {'ok' if self.ok else 'problem'}"


class ProviderConfig(models.Model):
    """A provider's key stored through the admin (ADR 0008), or a provider added there.

    Built-in providers (settings.AI_PROVIDERS) get a row only when a key is stored for them; their address
    stays in settings. Added providers are OpenAI-compatible endpoints with their own address.
    Keys are stored encrypted (apps.ai.secrets) and never shown again; `*_hint` keeps the last characters.
    """

    class Billing(models.TextChoices):
        AUTO = "", "Usual for this provider"
        PER_TOKEN = "per_token", "Pay per token"
        FREE_TIER = "free_tier", "Free tier"
        SUBSCRIPTION = "subscription", "Subscription (flat fee)"

    name = models.SlugField(
        max_length=30, unique=True, help_text="Short id used in the code, e.g. openrouter"
    )
    label = models.CharField(max_length=80)
    base_url = models.URLField(blank=True, help_text="Only for added providers")
    billing = models.CharField(
        max_length=20,
        choices=Billing.choices,
        blank=True,
        default="",
        db_default="",  # rows saved by code from before this field still get a value
        help_text="How this key is billed: prices become costs only for pay-per-token keys",
    )
    api_key_encrypted = models.TextField(blank=True, editable=False)
    api_key_hint = models.CharField(max_length=12, blank=True, editable=False)
    account_id_encrypted = models.TextField(blank=True, editable=False)  # Cloudflare
    account_id_hint = models.CharField(max_length=12, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["label"]

    def __str__(self):
        return self.label or self.name

    @property
    def built_in(self):
        return self.name in settings.AI_PROVIDERS


class AddedModel(models.Model):
    """A model offered in the dropdowns in addition to apps.ai.catalog: added by hand, or listed by the
    provider for a stored key (apps.ai.remote_models.sync). A listed model that is removed stays as a hidden
    row, so the next sync doesn't bring it back."""

    class Status(models.TextChoices):
        FREE = "free", "Free"
        LIMITED = "limited", "Free with limits"
        PAID = "paid", "Paid (billed to your key)"

    class Source(models.TextChoices):
        MANUAL = "manual", "Added by hand"
        LISTED = "listed", "Listed by the provider"

    provider = models.CharField(max_length=30)
    model = models.CharField(max_length=200, help_text="The provider's model id, e.g. openai/gpt-5.5")
    label = models.CharField(max_length=80)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PAID)
    typical_seconds = models.PositiveIntegerField(
        null=True, blank=True, help_text="Rough time per step in seconds, shown next to the model"
    )
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    hidden = models.BooleanField(default=False, help_text="Removed from the lists; kept so a sync skips it")
    details = models.CharField(
        max_length=200, blank=True, help_text="Context and price, as the provider lists"
    )
    refreshed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["provider", "label"]
        constraints = [models.UniqueConstraint(fields=["provider", "model"], name="ai_addedmodel_unique")]

    def __str__(self):
        return f"{self.label} ({self.provider})"


class ModelInfo(models.Model):
    """Price per million tokens and context window of one model (apps.ai.pricing), for built-in, listed
    and hand-added models alike. Filled by the model sync from the first source that has each value: a
    value entered by hand (never overwritten), the provider's own list, the reference price list. A blank
    value is unknown: nothing is guessed."""

    class Source(models.TextChoices):
        NONE = "", "Unknown"
        PROVIDER = "provider", "Provider's list"
        REFERENCE = "reference", "Reference price list"
        MANUAL = "manual", "Entered by hand"

    provider = models.CharField(max_length=30)
    model = models.CharField(max_length=200)
    input_per_m = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    output_per_m = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    cached_input_per_m = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    context_window = models.PositiveIntegerField(null=True, blank=True)
    max_output = models.PositiveIntegerField(null=True, blank=True)
    price_source = models.CharField(max_length=10, choices=Source.choices, blank=True, default="")
    context_source = models.CharField(max_length=10, choices=Source.choices, blank=True, default="")
    note = models.CharField(max_length=200, blank=True, help_text="Where a reference value was matched")
    checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["provider", "model"]
        constraints = [models.UniqueConstraint(fields=["provider", "model"], name="ai_modelinfo_unique")]

    def __str__(self):
        return f"{self.provider}::{self.model}"


class PriceReference(models.Model):
    """The reference price list (LiteLLM's model_prices_and_context_window.json, MIT), reduced to chat
    models: {key: {provider, in, out, cached, context, max_output}} with prices per token."""

    url = models.URLField()
    entries = models.JSONField(default=dict)
    fetched_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return f"{len(self.entries)} reference prices"


class UsageRecord(models.Model):
    """One model call: tokens used and what it cost (apps.ai.usage). `cost_kind` says how sure the cost
    is: billed (the provider reported it), estimated (tokens x price), free (free tier, local or a flat
    subscription), or unknown (no price)."""

    class CostKind(models.TextChoices):
        BILLED = "billed", "Billed"
        ESTIMATED = "estimated", "Estimated"
        FREE = "free", "Free"
        UNKNOWN = "unknown", "Unknown"

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    provider = models.CharField(max_length=30)
    model = models.CharField(max_length=200)
    kind = models.CharField(max_length=20, blank=True, help_text="step, chat, image_plan, image_job, other")
    run_id = models.PositiveIntegerField(null=True, blank=True, db_index=True)
    step_key = models.CharField(max_length=30, blank=True)
    object_id = models.PositiveIntegerField(null=True, blank=True, help_text="The step, chat or job id")
    input_tokens = models.PositiveIntegerField(null=True, blank=True)
    output_tokens = models.PositiveIntegerField(null=True, blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    cost_kind = models.CharField(max_length=10, choices=CostKind.choices, default=CostKind.UNKNOWN)
    seconds = models.FloatField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.provider}/{self.model}: {self.input_tokens} in, {self.output_tokens} out"


class KeywordSource(models.Model):
    """A keyword data platform (Settings › Keyword data providers): its key, and for DataForSEO its login.
    The Search results step asks the first enabled source with a key (by `order`) for each candidate
    keyword's volume, difficulty, intent and CPC (apps.studio.keyword_data). Keys are encrypted like the
    provider keys (apps.ai.secrets) and never shown again."""

    class Platform(models.TextChoices):
        SEMRUSH = "semrush", "Semrush"
        DATAFORSEO = "dataforseo", "DataForSEO"
        KEYWORDS_EVERYWHERE = "keywords_everywhere", "Keywords Everywhere"
        OTHER = "other", "Other (key stored; no reader yet)"

    name = models.SlugField(max_length=40, unique=True, help_text="Short id, e.g. semrush")
    label = models.CharField(max_length=80)
    platform = models.CharField(max_length=30, choices=Platform.choices, default=Platform.OTHER)
    base_url = models.URLField(blank=True, help_text="Only to override the platform's API address")
    api_key_encrypted = models.TextField(blank=True, editable=False)
    api_key_hint = models.CharField(max_length=12, blank=True, editable=False)
    login_encrypted = models.TextField(blank=True, editable=False)  # DataForSEO: API login
    login_hint = models.CharField(max_length=12, blank=True, editable=False)
    enabled = models.BooleanField(default=True)
    order = models.PositiveSmallIntegerField(default=10, help_text="Lower is asked first")
    notes = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["order", "label"]

    def __str__(self):
        return self.label

    @property
    def needs_login(self):
        return self.platform == self.Platform.DATAFORSEO

    @property
    def readable(self):
        return self.platform != self.Platform.OTHER

    @property
    def ready(self):
        """Enabled, with the platform's credentials stored, and a reader for it."""
        return bool(
            self.enabled
            and self.readable
            and self.api_key_encrypted
            and (self.login_encrypted or not self.needs_login)
        )


class KeywordRules(models.Model):
    """How candidate keywords are filtered before research sees them (one row; apps.studio.keyword_data).
    Volume and difficulty apply only where a keyword source measured them."""

    min_volume = models.PositiveIntegerField(default=10, help_text="Monthly searches; lower is dropped")
    max_difficulty = models.PositiveSmallIntegerField(
        default=70, help_text="Keyword difficulty 0-100; higher is dropped"
    )
    drop_navigational = models.BooleanField(
        default=True, help_text="Drop keywords whose intent is navigational (someone looking for one site)"
    )
    exclude_terms = models.TextField(
        blank=True, help_text="Words or phrases that drop a keyword, one per line (e.g. competitor names)"
    )
    max_keywords = models.PositiveSmallIntegerField(
        default=25, help_text="Keywords kept for research, at most"
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    def __str__(self):
        return "Keyword rules"

    @classmethod
    def current(cls):
        from django.db import DatabaseError

        try:
            return cls.objects.first() or cls()
        except DatabaseError:
            return cls()

    def excluded(self):
        return [line.strip().lower() for line in self.exclude_terms.splitlines() if line.strip()]


class ModelSync(models.Model):
    """When a provider's model list was last read into AddedModel, and what went wrong if it failed."""

    provider = models.CharField(max_length=30, unique=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    listed = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return f"{self.provider}: {self.listed} models"


class TaskDefault(models.Model):
    """The default model (and fallback) an admin chose for one task under Settings › Default models.

    It takes the place of the task's profile in settings.AI_PROFILES (apps.ai.defaults). An empty key keeps
    the built-in choice. Values are "provider::model", as in the wizard's dropdowns.
    """

    task = models.SlugField(max_length=30, unique=True)
    model_key = models.CharField(max_length=240, blank=True)
    fallback_key = models.CharField(max_length=240, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    def __str__(self):
        return f"{self.task}: {self.model_key or 'built-in'}"
