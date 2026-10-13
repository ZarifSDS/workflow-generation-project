from django.db import models


class ProviderCheck(models.Model):
    """Result of the last availability check per provider, shown on the Models and providers screen."""

    provider = models.CharField(max_length=30, unique=True)
    ok = models.BooleanField(default=False)
    detail = models.CharField(max_length=500, blank=True)
    checked_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.provider}: {'ok' if self.ok else 'problem'}"
