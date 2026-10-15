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

from apps.ai import catalog, pricing, remote_models, secrets
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

    home = ("studio:provider_keys", "AI providers")  # the settings page this one belongs to

    def get_breadcrumbs_items(self):
        url_name, label = self.home
        items = [{"url": reverse(url_name), "label": label}]
        if self.page_title != label:
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


def is_search(name):
    """Search data providers (Serper, Brave, Google Programmable Search) have their own settings page."""
    return settings.AI_PROVIDERS.get(name, {}).get("adapter") == "search"


def home_for(name):
    if is_search(name):
        return ("studio:search_providers", "Search data providers")
    return ("studio:provider_keys", "AI providers")


def _row_for(name, label):
    row, _ = ProviderConfig.objects.get_or_create(name=name, defaults={"label": label})
    return row


def _set_secret(row, field, value):
    setattr(row, f"{field}_encrypted", secrets.encrypt(value))
    setattr(row, f"{field}_hint", secrets.hint(value))


def _clear_secret(row, field):
    setattr(row, f"{field}_encrypted", "")
    setattr(row, f"{field}_hint", "")


def sync_message(name, label):
    """List the provider's models now (a new or changed key means a new list) and say what happened."""
    spec = get_providers().get(name)
    if spec is None or not remote_models.listable(spec):
        return ""
    try:
        count = remote_models.sync(spec)
    except remote_models.RemoteModelsError as error:
        return f" Its models couldn't be listed yet ({error}); add them under Add a model, or refresh later."
    return f" {count} of its models are in the model lists now." if count else ""


class ProviderKeysView(KeysPage):
    template_name = "studio/provider_keys.html"
    page_title = "AI providers"
    search = False  # True on Settings › Search data providers

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        stored = {row.name: row for row in ProviderConfig.objects.select_related("updated_by")}
        providers = []
        for name, spec in get_providers().items():
            if is_search(name) != self.search:
                continue
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
        if not self.search:
            from apps.ai.models import PriceReference

            context.update(
                model_lists=self.model_lists(providers),
                billing_choices=[(v, label) for v, label in ProviderConfig.Billing.choices if v],
                reference=PriceReference.objects.first(),
            )
            self.sync_stale_in_background()
        context.update(
            providers=providers,
            labels=catalog.provider_labels() | {p["name"]: p["label"] for p in providers},
        )
        return context

    def model_lists(self, providers):
        """Per text provider: models in the lists (listed, by hand, hidden) and the last sync."""
        from django.db.models import Count, Q

        from apps.ai.models import ModelInfo, ModelSync

        counts = {
            row["provider"]: row
            for row in AddedModel.objects.values("provider").annotate(
                listed=Count("pk", filter=Q(source="listed", hidden=False)),
                manual=Count("pk", filter=Q(source="manual", hidden=False)),
                hidden=Count("pk", filter=Q(hidden=True)),
            )
        }
        syncs = {row.provider: row for row in ModelSync.objects.all()}
        priced, known = {}, {}
        for row in ModelInfo.objects.values("provider", "input_per_m", "context_window"):
            known[row["provider"]] = known.get(row["provider"], 0) + 1
            if row["input_per_m"] is not None:
                priced[row["provider"]] = priced.get(row["provider"], 0) + 1
        built_in = {}
        for item in catalog.CATALOG:
            if item.kind == "text":
                built_in[item.provider] = built_in.get(item.provider, 0) + 1
        rows = []
        for p in providers:
            spec = p["spec"]
            if spec.adapter not in TEXT_ADAPTERS:
                continue
            count = counts.get(p["name"], {})
            rows.append(
                {
                    **p,
                    "billing": pricing.billing(p["name"]),
                    "billing_choice": p["row"].billing if p["row"] else "",
                    "usual_label": pricing.BILLING_LABELS[pricing.USUAL_BILLING.get(p["name"], "per_token")],
                    "local": pricing.USUAL_BILLING.get(p["name"]) == pricing.LOCAL,
                    "priced": priced.get(p["name"], 0),
                    "known": known.get(p["name"], 0),
                    "listable": remote_models.listable(spec),
                    "built_in": built_in.get(p["name"], 0),
                    "listed": count.get("listed", 0),
                    "manual": count.get("manual", 0),
                    "hidden": count.get("hidden", 0),
                    "sync": syncs.get(p["name"]),
                }
            )
        return rows

    def sync_stale_in_background(self):
        """Lists older than a day are read again by the worker (the page never waits for a provider)."""
        if not getattr(settings, "STUDIO_EXECUTE_STEPS", False):
            return
        from django.core.cache import cache

        stale = remote_models.stale()
        # cache.add is false while a sync queued in the last ten minutes may still be waiting for the worker.
        if stale and cache.add("ai:model-sync-queued", True, 600):
            from ..tasks import sync_model_lists

            transaction.on_commit(lambda: sync_model_lists.enqueue(stale))

    def post(self, request, *args, **kwargs):
        """Refresh the model lists of every provider that can list its models (or one: ?provider=), or
        save how each key is billed."""
        if not self.search and request.POST.get("action") == "billing":
            return self.save_billing(request)
        if self.search or request.POST.get("action") != "refresh":
            return redirect("studio:provider_keys")
        only = request.POST.get("provider") or None
        results = remote_models.sync_all([only] if only else None)
        labels = catalog.provider_labels()
        done = [f"{labels.get(n, n)} {r}" for n, r in results.items() if isinstance(r, int)]
        failed = [f"{labels.get(n, n)} ({r})" for n, r in results.items() if not isinstance(r, int)]
        if done:
            messages.success(request, "Model lists refreshed: " + ", ".join(done) + " models.")
        if failed:
            messages.error(request, "Couldn't list the models of " + "; ".join(failed) + ".")
        if not results:
            messages.info(request, "No provider with a key lists its models yet.")
        return redirect("studio:provider_keys")

    def save_billing(self, request):
        valid = set(ProviderConfig.Billing.values)
        changed = []
        with transaction.atomic():
            for name, spec in get_providers().items():
                if spec.adapter not in TEXT_ADAPTERS or pricing.USUAL_BILLING.get(name) == pricing.LOCAL:
                    continue
                value = request.POST.get(f"billing-{name}")
                if value is None or value not in valid:
                    continue
                row = ProviderConfig.objects.filter(name=name).first()
                if (row.billing if row else "") == value:
                    continue
                row = row or _row_for(name, self.label_for(name, spec))
                row.billing, row.updated_by = value, request.user
                row.save()
                log(instance=row, action="ai.billing_set", user=request.user, data={"billing": value})
                changed.append(row.label)
        pricing.clear_cache()
        messages.success(
            request, f"Saved how {', '.join(changed)} is billed." if changed else "Nothing changed."
        )
        return redirect("studio:provider_keys")


class ProviderKeyView(KeysPage):
    """Set or replace a provider's key (and Cloudflare's account ID)."""

    template_name = "studio/provider_key_form.html"

    def prepare(self, **kwargs):
        self.spec = get_providers().get(kwargs["name"])
        if self.spec is None or not (self.spec.needs_key or self.spec.account_env):
            raise Http404
        self.page_title = f"Key for {self.label_for(self.spec.name, self.spec)}"
        self.home = home_for(self.spec.name)

    def get_form(self):
        return KeyForm(
            self.request.POST or None,
            needs_account=bool(self.spec.account_env),
            required=not self.spec.account_env,
            account_label=self.spec.account_label,
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
        note = sync_message(row.name, row.label) if form.cleaned_data.get("api_key") else ""
        messages.success(
            request, f"Saved {' and '.join(changed)} for {row.label}. It's used from now on.{note}"
        )
        return redirect(home_for(row.name)[0])


class ConfirmView(KeysPage):
    """GET shows what will be removed; POST removes it."""

    template_name = "studio/provider_confirm.html"
    question = ""
    detail = ""
    button = "Remove"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            question=self.question, detail=self.detail, button=self.button, cancel_url=reverse(self.home[0])
        )
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
        self.home = home_for(self.row.name)

    def post(self, request, *args, **kwargs):
        row = self.row
        with transaction.atomic():
            log(instance=row, action="ai.key_removed", user=request.user)
            if row.built_in and not row.billing:
                row.delete()  # nothing else is stored for a built-in provider
            else:
                _clear_secret(row, "api_key")
                _clear_secret(row, "account_id")
                row.updated_by = request.user
                row.save()
        messages.success(request, f"Removed the stored key for {row.label}.")
        return redirect(home_for(row.name)[0])


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
        listed = sync_message(row.name, row.label) if row.api_key_encrypted else ""
        messages.success(
            request,
            f"{verb} {row.label}.{listed or ' Add its models below to offer them in the studio.'}{note}",
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
    """Pick the provider, then one of the models it lists (apps.ai.remote_models); typing an id stays
    possible for a model the list doesn't show."""

    template_name = "studio/provider_model_form.html"
    page_title = "Choose models"

    def prepare(self, **kwargs):
        self.providers = {
            name: spec for name, spec in get_providers().items() if spec.adapter in TEXT_ADAPTERS
        }
        chosen = self.request.POST.get("provider") or self.request.GET.get("provider", "")
        self.provider = chosen if chosen in self.providers else ""
        # Opened from Settings › Default models: go back there after adding (that page only).
        self.return_to = (
            "defaults" if (self.request.POST or self.request.GET).get("return_to") == "defaults" else ""
        )
        self.remote, self.remote_error = [], ""
        if self.provider:
            try:
                self.remote = remote_models.list_models(
                    self.providers[self.provider], refresh=self.request.GET.get("refresh") == "1"
                )
            except remote_models.RemoteModelsError as error:
                self.remote_error = f"Couldn't list its models: {error}. Type the model id instead."

    def built_in(self):
        return [item for item in catalog.CATALOG if item.provider == self.provider and item.kind == "text"]

    def provider_choices(self):
        return [("", "Choose a provider")] + [
            (name, self.label_for(name, spec)) for name, spec in self.providers.items()
        ]

    def get_form(self):
        return AddedModelForm(
            self.request.POST or None,
            initial={"provider": self.provider},
            provider_choices=self.provider_choices(),
            remote=self.remote,
            rows=list(AddedModel.objects.filter(provider=self.provider)),
            built_in=[item.model for item in self.built_in()],
            default_status=catalog.usual_status(self.provider) if self.provider else "paid",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            form=kwargs.get("form") or self.get_form(),
            provider=self.provider,
            provider_label=self.label_for(self.provider, self.providers.get(self.provider))
            if self.provider
            else "",
            remote_count=len(self.remote),
            remote_error=self.remote_error,
            return_to=self.return_to,
            built_in_models=self.built_in() if self.provider else [],
        )
        return context

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        added, removed = form.save()
        for row in added:
            log(instance=row, action="ai.model_added", user=request.user)
        catalog.clear_cache()
        parts = []
        if added:
            names = ", ".join(row.label for row in added[:5])
            parts.append(f"Added {names}{f' and {len(added) - 5} more' if len(added) > 5 else ''}.")
        if removed:
            parts.append(f"Removed {removed} model{'s' if removed != 1 else ''} from the lists.")
        messages.success(request, " ".join(parts))
        if request.POST.get("next") == "another":
            back = "&return_to=defaults" if self.return_to else ""
            return redirect(f"{reverse('studio:provider_model_add')}?provider={self.provider}{back}")
        return redirect("studio:task_defaults" if self.return_to else "studio:provider_keys")


class ModelsManageView(KeysPage):
    """Settings › AI providers › Manage models: rename, re-price, remove and restore models in bulk.

    Removing a model added by hand deletes it; removing a listed one hides it, so the next sync of the
    provider's list doesn't bring it back (Restore shows it again). The built-in catalog isn't edited here.
    """

    template_name = "studio/provider_models.html"
    page_title = "Manage models"
    LIMIT = 300

    def prepare(self, **kwargs):
        params = self.request.POST if self.request.method == "POST" else self.request.GET
        self.provider = params.get("provider", "")
        self.q = params.get("q", "").strip()
        self.show_hidden = params.get("hidden") == "1"

    def queryset(self):
        rows = AddedModel.objects.filter(hidden=self.show_hidden)
        if self.provider:
            rows = rows.filter(provider=self.provider)
        if self.q:
            from django.db.models import Q

            for word in self.q.split():
                rows = rows.filter(
                    Q(label__icontains=word) | Q(model__icontains=word) | Q(details__icontains=word)
                )
        return rows.order_by("provider", "label")

    def get_context_data(self, **kwargs):
        from apps.ai.models import ModelInfo

        context = super().get_context_data(**kwargs)
        rows = self.queryset()
        labels = catalog.provider_labels()
        providers = sorted(set(AddedModel.objects.values_list("provider", flat=True)))
        shown = list(rows[: self.LIMIT])
        infos = {
            (i.provider, i.model): i for i in ModelInfo.objects.filter(model__in=[m.model for m in shown])
        }
        for row in shown:
            row.info = infos.get((row.provider, row.model))
        context.update(
            rows=shown,
            total=rows.count(),
            limit=self.LIMIT,
            provider=self.provider,
            q=self.q,
            show_hidden=self.show_hidden,
            providers=[(name, labels.get(name, name)) for name in providers],
            labels=labels,
            statuses=AddedModel.Status.choices,
        )
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        picked = [int(pk) for pk in request.POST.getlist("pick") if pk.isdigit()]
        from urllib.parse import urlencode

        query = {"provider": self.provider, "q": self.q, **({"hidden": "1"} if self.show_hidden else {})}
        back = f"{reverse('studio:provider_models')}?{urlencode(query)}"
        if action == "save":
            changed = self._save_edits(request)
            messages.success(
                request,
                f"Saved {changed} change{'s' if changed != 1 else ''}." if changed else "Nothing changed.",
            )
        elif action in ("remove", "restore") and picked:
            rows = AddedModel.objects.filter(pk__in=picked)
            with transaction.atomic():
                if action == "restore":
                    count = rows.update(hidden=False)
                    verb = "Restored"
                else:
                    manual = rows.filter(source=AddedModel.Source.MANUAL)
                    count = manual.count() + rows.filter(source=AddedModel.Source.LISTED).update(hidden=True)
                    for row in manual:
                        log(instance=row, action="ai.model_removed", user=request.user)
                    manual.delete()
                    verb = "Removed"
            catalog.clear_cache()
            messages.success(request, f"{verb} {count} model{'s' if count != 1 else ''}.")
        else:
            messages.error(request, "Tick the models first.")
        return redirect(back)

    def _save_edits(self, request):
        changed = 0
        valid = set(AddedModel.Status.values)
        rows = AddedModel.objects.filter(
            pk__in=[int(pk) for pk in request.POST.getlist("row") if pk.isdigit()]
        )
        with transaction.atomic():
            for row in rows:
                label = " ".join(request.POST.get(f"label-{row.pk}", row.label).split())[:80] or row.label
                status = request.POST.get(f"status-{row.pk}", row.status)
                if status not in valid:
                    status = row.status
                if (label, status) != (row.label, row.status):
                    row.label, row.status = label, status
                    row.save(update_fields=["label", "status"])
                    changed += 1
                changed += _save_prices(request, row)
        catalog.clear_cache()
        pricing.clear_cache()
        return changed


def _number(text, kind):
    """A typed price (USD per million) or context window; "" clears it; None when it doesn't parse."""
    from decimal import Decimal, InvalidOperation

    text = (text or "").strip().replace("$", "").replace(",", "")
    if not text:
        return ""
    if kind == "context":
        text = text.lower().removesuffix("tokens").strip()
        scale = 1000 if text.endswith("k") else 1_000_000 if text.endswith("m") else 1
        try:
            value = int(Decimal(text.rstrip("km")) * scale)
        except InvalidOperation:
            return None
        return value if value > 0 else None
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    return value if value >= 0 else None


def _save_prices(request, row):
    """Prices and context typed on Manage models: a change is stored as entered by hand (a sync never
    overwrites it); clearing every field hands the model back to the automatic sources. Returns 1 when
    something changed."""
    from apps.ai.models import ModelInfo

    fields = {
        "in": request.POST.get(f"in-{row.pk}"),
        "out": request.POST.get(f"out-{row.pk}"),
        "ctx": request.POST.get(f"ctx-{row.pk}"),
    }
    if all(value is None for value in fields.values()):
        return 0
    info = ModelInfo.objects.filter(provider=row.provider, model=row.model).first()
    shown = {
        "in": _shown(info.input_per_m if info else None),
        "out": _shown(info.output_per_m if info else None),
        "ctx": str(info.context_window) if info and info.context_window else "",
    }
    typed = {key: (value or "").strip() for key, value in fields.items()}
    if typed == shown:
        return 0
    info = info or ModelInfo(provider=row.provider, model=row.model)
    price_in, price_out = _number(typed["in"], "price"), _number(typed["out"], "price")
    if (typed["in"], typed["out"]) != (shown["in"], shown["out"]):
        if price_in == "" and price_out == "":
            info.input_per_m = info.output_per_m = info.cached_input_per_m = None
            info.price_source = ""
        elif price_in not in (None, "") and price_out not in (None, ""):
            info.input_per_m, info.output_per_m, info.price_source = price_in, price_out, "manual"
        else:
            messages.error(request, f"{row.label}: enter both prices per million tokens, or neither.")
    if typed["ctx"] != shown["ctx"]:
        context = _number(typed["ctx"], "context")
        if context == "":
            info.context_window, info.context_source = None, ""
        elif context is None:
            messages.error(request, f"{row.label}: the context window should be a number of tokens.")
        else:
            info.context_window, info.context_source = context, "manual"
    info.save()
    return 1


def _shown(value):
    """A stored price as the Manage models field shows it (no trailing zeros)."""
    if value is None:
        return ""
    return format(value.normalize(), "f")


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


class UsageView(KeysPage):
    """Settings › AI providers › Usage and cost: tokens and cost from the usage ledger (apps.ai.usage), by
    month, provider and model, and the latest runs."""

    template_name = "studio/usage.html"
    page_title = "Usage and cost"
    header_icon = "table"

    def get_context_data(self, **kwargs):
        from django.db.models import Count, Max, Q, Sum
        from django.db.models.functions import TruncMonth

        from apps.ai.models import UsageRecord

        from ..models import GenerationRun

        context = super().get_context_data(**kwargs)
        labels = catalog.provider_labels()
        months = {}
        rows = (
            UsageRecord.objects.annotate(month=TruncMonth("created_at"))
            .values("month", "provider", "model")
            .annotate(
                calls=Count("pk"),
                tokens_in=Sum("input_tokens"),
                tokens_out=Sum("output_tokens"),
                cost=Sum("cost"),
                unknown=Count("pk", filter=Q(cost_kind="unknown")),
                estimated=Count("pk", filter=Q(cost_kind="estimated")),
                billed=Count("pk", filter=Q(cost_kind="billed")),
            )
            .order_by("-month", "-cost")
        )
        for row in rows:
            row["label"] = labels.get(row["provider"], row["provider"])
            row["how"] = next((kind for kind in ("unknown", "estimated", "billed") if row[kind]), "free")
            month = months.setdefault(row["month"], {"month": row["month"], "rows": [], "cost": 0})
            month["rows"].append(row)
            month["cost"] += row["cost"] or 0
        runs = (
            UsageRecord.objects.filter(run_id__isnull=False)
            .values("run_id")
            .annotate(
                calls=Count("pk"), cost=Sum("cost"), tokens_in=Sum("input_tokens"), last=Max("created_at")
            )
            .order_by("-last")[:15]
        )
        topics = dict(
            GenerationRun.objects.filter(pk__in=[r["run_id"] for r in runs]).values_list("pk", "brief__topic")
        )
        for run in runs:
            run["topic"] = topics.get(run["run_id"], f"Run {run['run_id']}")
        context.update(months=list(months.values()), runs=list(runs))
        return context


class SearchProvidersView(ProviderKeysView):
    """Settings › Search data providers: keys for the Search results step (apps/studio/serp.py)."""

    template_name = "studio/search_providers.html"
    page_title = "Search data providers"
    header_icon = "search"
    search = True
    home = ("studio:search_providers", "Search data providers")

    FREE_TIERS = {
        "serper": "Google results by country and language; free starting credits, then paid.",
        "brave_search": "Brave's own index by country and language; free monthly tier.",
        "google_cse": (
            "Google Programmable Search; about 100 free queries a day. Needs a key and a search engine ID."
        ),
    }

    def get_context_data(self, **kwargs):
        from .. import serp

        context = super().get_context_data(**kwargs)
        for provider in context["providers"]:
            provider["free_tier"] = self.FREE_TIERS.get(provider["name"], "")
        ollama = get_providers().get("ollama_cloud")
        context.update(
            order=settings.STUDIO_SERP_PROVIDERS,
            in_use=serp.configured_providers(),
            ollama_ready=bool(ollama and ollama.is_configured),
            pages=settings.STUDIO_SERP_PAGES,
        )
        return context

    def post(self, request, *args, **kwargs):
        """Test search: one query through the first provider that answers."""
        from .. import serp

        try:
            data = serp.search("safety data sheet requirements", "US", num=5)
            messages.success(
                request,
                f"{data.provider} answered with {len(data.results)} results. "
                "The Search results step will use it.",
            )
        except serp.SerpError as error:
            messages.error(request, str(error)[:400])
        return redirect("studio:search_providers")
