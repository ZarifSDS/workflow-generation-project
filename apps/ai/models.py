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

    name = models.SlugField(
        max_length=30, unique=True, help_text="Short id used in the code, e.g. openrouter"
    )
    label = models.CharField(max_length=80)
    base_url = models.URLField(blank=True, help_text="Only for added providers")
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
