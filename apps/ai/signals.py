"""Clear the caches built from admin-stored providers and models when they change (ADR 0008)."""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from . import catalog, defaults, redact
from .models import AddedModel, ProviderConfig, TaskDefault


@receiver([post_save, post_delete], sender=ProviderConfig)
@receiver([post_save, post_delete], sender=AddedModel)
def clear_caches(**kwargs):
    catalog.clear_cache()
    redact.clear_stored_cache()


@receiver([post_save, post_delete], sender=TaskDefault)
def clear_defaults_cache(**kwargs):
    defaults.clear_cache()
