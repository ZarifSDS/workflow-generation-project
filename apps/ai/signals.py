"""Clear the caches built from admin-stored providers and models when they change (ADR 0008)."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from . import catalog, redact
from .models import AddedModel, ProviderConfig


@receiver([post_save, post_delete], sender=ProviderConfig)
@receiver([post_save, post_delete], sender=AddedModel)
def clear_caches(**kwargs):
    catalog.clear_cache()
    redact.clear_stored_cache()
