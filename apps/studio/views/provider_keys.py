"""Settings › AI providers: store, replace and remove provider API keys, add providers and models.

Superusers only (ADR 0008). Keys are encrypted (apps.ai.secrets), never rendered back, and shown only as
their last characters. Every change is recorded in Wagtail's history (Reports › Site history), without
the key itself.
"""

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from wagtail.log_actions import log

from apps.ai import catalog, secrets
from apps.ai.forms import AddedModelForm, AddedProviderForm, KeyForm
from apps.ai.models import AddedModel, ProviderConfig
from apps.ai.providers import get_providers

from .common import StudioPage

TEXT_ADAPTERS = {"openai_compat", "ollama_native"}


@method_decorator(never_cache, name="dispatch")
class KeysPage(StudioPage):
    """Base: superusers only; responses are never cached."""

    header_icon = "key"

    def dispatch(self, request, *args, **kwargs):
        # Checked before any lookup, so other users can't probe which providers exist.
        if not request.user.is_superuser:
            raise PermissionDenied
        self.prepare(**kwargs)
        return super().dispatch(request, *args, **kwargs)

    def prepare(self, **kwargs):
        """Load what the page is about (after the permission check)."""

    def get_breadcrumbs_items(self):
        items = [{"url": reverse("studio:provider_keys"), "label": "AI providers"}]
        if self.page_title != "AI providers":
            items.append({"url": "", "label": self.page_title})
        return items

    def label_for(self, name, spec=None):
        if spec is not None and spec.label:
            return spec.label
        return catalog.provider_label(name)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(secrets_ready=secrets.available(), secrets_env=secrets.ENV_NAME)
        return context


def _row_for(name, label):
    row, _ = ProviderConfig.objects.get_or_create(name=name, defaults={"label": label})
    return row


def _set_secret(row, field, value):
    setattr(row, f"{field}_encrypted", secrets.encrypt(value))
    setattr(row, f"{field}_hint", secrets.hint(value))


def _clear_secret(row, field):
    setattr(row, f"{field}_encrypted", "")
    setattr(row, f"{field}_hint", "")


class ProviderKeysView(KeysPage):
    template_name = "studio/provider_keys.html"
    page_title = "AI providers"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stored = {row.name: row for row in ProviderConfig.objects.select_related("updated_by")}
        providers = []
        for name, spec in get_providers().items():
            row = stored.get(name)
            env_value = spec.api_key if spec.key_source == "env" else ""
            providers.append(
                {
                    "name": name,
                    "label": self.label_for(name, spec),
                    "spec": spec,
                    "row": row,
                    "added": spec.added,
                    "needs_key": spec.needs_key or bool(spec.account_env),
                    "source": spec.key_source,
                    "hint": row.api_key_hint if row and row.api_key_hint else secrets.hint(env_value),
                    "account_hint": row.account_id_hint if row else "",
                    "base_url": spec.base_url,
                }
            )
        context.update(
            providers=providers,
            added_models=AddedModel.objects.all(),
            labels=catalog.provider_labels() | {p["name"]: p["label"] for p in providers},
        )
        return context


class ProviderKeyView(KeysPage):
    """Set or replace a provider's key (and Cloudflare's account ID)."""

    template_name = "studio/provider_key_form.html"

    def prepare(self, **kwargs):
        self.spec = get_providers().get(kwargs["name"])
        if self.spec is None or not (self.spec.needs_key or self.spec.account_env):
            raise Http404
        self.page_title = f"Key for {self.label_for(self.spec.name, self.spec)}"

    def get_form(self):
        return KeyForm(
            self.request.POST or None,
            needs_account=bool(self.spec.account_env),
            required=not self.spec.account_env,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(form=kwargs.get("form") or self.get_form(), spec=self.spec)
        return context

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if not secrets.available():
            messages.error(request, f"Add {secrets.ENV_NAME} to .env first (see the note on this page).")
            return self.render_to_response(self.get_context_data(form=form))
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        with transaction.atomic():
            row = _row_for(self.spec.name, self.label_for(self.spec.name, self.spec))
            changed = []
            if form.cleaned_data.get("api_key"):
                _set_secret(row, "api_key", form.cleaned_data["api_key"])
                changed.append(f"API key {row.api_key_hint}")
            if form.cleaned_data.get("account_id"):
                _set_secret(row, "account_id", form.cleaned_data["account_id"])
                changed.append(f"account ID {row.account_id_hint}")
            row.updated_by = request.user
            row.save()
            log(instance=row, action="ai.key_set", user=request.user, data={"changed": changed})
        messages.success(request, f"Saved {' and '.join(changed)} for {row.label}. It's used from now on.")
        return redirect("studio:provider_keys")


class ConfirmView(KeysPage):
    """GET shows what will be removed; POST removes it."""

    template_name = "studio/provider_confirm.html"
    question = ""
    detail = ""
    button = "Remove"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(question=self.question, detail=self.detail, button=self.button)
        return context


class RemoveKeyView(ConfirmView):
    def prepare(self, **kwargs):
        self.row = get_object_or_404(ProviderConfig, name=kwargs["name"])
        if not (self.row.api_key_encrypted or self.row.account_id_encrypted):
            raise Http404
        self.page_title = f"Remove the key for {self.row.label}"
        self.question = f"Remove the stored key for {self.row.label}?"
        env = settings.AI_PROVIDERS.get(self.row.name, {}).get("api_key_env")
        self.detail = (
            f"The studio goes back to {env} from .env, if it's set there."
            if env
            else "The provider stays in the list but can't be used until you enter a key again."
        )
        self.button = "Remove key"

    def post(self, request, *args, **kwargs):
        row = self.row
        with transaction.atomic():
            log(instance=row, action="ai.key_removed", user=request.user)
            if row.built_in:
                row.delete()  # nothing else is stored for a built-in provider
            else:
                _clear_secret(row, "api_key")
                _clear_secret(row, "account_id")
                row.updated_by = request.user
                row.save()
        messages.success(request, f"Removed the stored key for {row.label}.")
        return redirect("studio:provider_keys")


class AddedProviderView(KeysPage):
    """Add an OpenAI-compatible provider, or edit one that was added."""

    template_name = "studio/provider_key_form.html"

    def prepare(self, **kwargs):
        name = kwargs.get("name")
        self.instance = None
        if name:
            self.instance = get_object_or_404(ProviderConfig, name=name)
            if self.instance.built_in:
                raise Http404
        self.page_title = f"Edit {self.instance.label}" if self.instance else "Add a provider"

    def get_form(self):
        return AddedProviderForm(self.request.POST or None, instance=self.instance)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(form=kwargs.get("form") or self.get_form(), adding=self.instance is None)
        return context

    def post(self, request, *args, **kwargs):
        old_url = self.instance.base_url if self.instance else None
        form = self.get_form()
        if not secrets.available():
            messages.error(request, f"Add {secrets.ENV_NAME} to .env first (see the note on this page).")
            return self.render_to_response(self.get_context_data(form=form))
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        with transaction.atomic():
            row = form.save(commit=False)
            key = form.cleaned_data.get("api_key")
            note = ""
            if key:
                _set_secret(row, "api_key", key)
            elif old_url is not None and row.base_url != old_url and row.api_key_encrypted:
                _clear_secret(row, "api_key")
                note = " The address changed, so the stored key was removed; enter it again."
            row.updated_by = request.user
            row.save()
            log(
                instance=row,
                action="ai.provider_added" if old_url is None else "ai.provider_changed",
                user=request.user,
                data={"base_url": row.base_url, "key": row.api_key_hint or "none"},
            )
        verb = "Added" if old_url is None else "Saved"
        messages.success(
            request, f"{verb} {row.label}. Add its models below to offer them in the studio.{note}"
        )
        return redirect("studio:provider_keys")


class DeleteProviderView(ConfirmView):
    def prepare(self, **kwargs):
        self.row = get_object_or_404(ProviderConfig, name=kwargs["name"])
        if self.row.built_in:
            raise Http404
        count = AddedModel.objects.filter(provider=self.row.name).count()
        self.page_title = f"Delete {self.row.label}"
        self.question = f"Delete {self.row.label} and its stored key?"
        self.detail = (
            f"Its {count} added model{'s' if count != 1 else ''} are removed too. "
            "Runs that already used it keep their output; steps set to one of its models fail until "
            "you pick another model."
        )
        self.button = "Delete provider"

    def post(self, request, *args, **kwargs):
        row = self.row
        with transaction.atomic():
            log(instance=row, action="ai.provider_deleted", user=request.user)
            AddedModel.objects.filter(provider=row.name).delete()
            row.delete()
        messages.success(request, f"Deleted {row.label}.")
        return redirect("studio:provider_keys")


class AddedModelView(KeysPage):
    template_name = "studio/provider_key_form.html"
    page_title = "Add a model"

    def provider_choices(self):
        return [
            (name, self.label_for(name, spec))
            for name, spec in get_providers().items()
            if spec.adapter in TEXT_ADAPTERS
        ]

    def get_form(self):
        initial = {"provider": self.request.GET.get("provider", "")}
        return AddedModelForm(
            self.request.POST or None, initial=initial, provider_choices=self.provider_choices()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(form=kwargs.get("form") or self.get_form(), adding=True, model_form=True)
        return context

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        item = form.save()
        log(instance=item, action="ai.model_added", user=request.user)
        messages.success(request, f"Added {item.label}. It's offered in the model lists now.")
        return redirect("studio:provider_keys")


class DeleteModelView(ConfirmView):
    def prepare(self, **kwargs):
        self.item = get_object_or_404(AddedModel, pk=kwargs["pk"])
        self.page_title = f"Remove {self.item.label}"
        self.question = f"Remove {self.item.label} from the model lists?"
        self.detail = "Steps already set to this model keep it until someone picks another one."
        self.button = "Remove model"

    def post(self, request, *args, **kwargs):
        log(instance=self.item, action="ai.model_removed", user=request.user)
        label = self.item.label
        self.item.delete()
        messages.success(request, f"Removed {label}.")
        return redirect("studio:provider_keys")
