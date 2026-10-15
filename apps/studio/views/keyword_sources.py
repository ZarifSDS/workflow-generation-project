"""Settings › Keyword data providers: keys for Semrush, DataForSEO, Keywords Everywhere and any platform
you add, plus the rules that filter keywords before research (apps/studio/keyword_data.py).

Superusers only, like the AI provider keys (ADR 0008): keys are encrypted, never shown again (only their
last characters), and every change is recorded under Reports › Site history without the key itself.
"""

from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from wagtail.log_actions import log

from apps.ai import secrets
from apps.ai.forms import KeywordRulesForm, KeywordSourceForm
from apps.ai.models import KeywordRules, KeywordSource

from .. import keyword_data
from .provider_keys import ConfirmView, KeysPage

HOME = ("studio:keyword_sources", "Keyword data providers")


class KeywordSourcesView(KeysPage):
    template_name = "studio/keyword_sources.html"
    page_title = "Keyword data providers"
    header_icon = "search"
    home = HOME

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        rules = KeywordRules.current()
        context.update(
            sources=list(KeywordSource.objects.select_related("updated_by")),
            ready=[s.name for s in keyword_data.sources()],
            rules_form=kwargs.get("rules_form") or KeywordRulesForm(instance=rules),
        )
        return context

    def post(self, request, *args, **kwargs):
        action = request.POST.get("action")
        if action == "rules":
            form = KeywordRulesForm(request.POST, instance=KeywordRules.current())
            if not form.is_valid():
                return self.render_to_response(self.get_context_data(rules_form=form))
            rules = form.save(commit=False)
            rules.updated_by = request.user
            rules.save()
            log(instance=rules, action="ai.keyword_rules_set", user=request.user)
            messages.success(request, "Saved the keyword rules. The next Search results step uses them.")
        elif action == "test":
            label, found, problems = keyword_data.measure(["safety data sheet"], "US")
            if label:
                metric = found.get("safety data sheet")
                detail = (
                    f": “safety data sheet” has {metric.volume:,} US searches a month"
                    if metric and metric.volume is not None
                    else ""
                )
                messages.success(request, f"{label} answered{detail}.")
            else:
                messages.error(
                    request,
                    "No keyword source answered"
                    + (f": {'; '.join(problems)}" if problems else ": none has a key yet."),
                )
        return redirect(HOME[0])


class KeywordSourceView(KeysPage):
    """Add a platform, or edit one: label, platform, address, order, on/off and its key."""

    template_name = "studio/keyword_source_form.html"
    home = HOME

    def prepare(self, **kwargs):
        self.instance = get_object_or_404(KeywordSource, name=kwargs["name"]) if kwargs.get("name") else None
        self.page_title = f"Edit {self.instance.label}" if self.instance else "Add a keyword platform"

    def get_form(self):
        return KeywordSourceForm(self.request.POST or None, instance=self.instance)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(form=kwargs.get("form") or self.get_form(), source=self.instance)
        return context

    def post(self, request, *args, **kwargs):
        form = self.get_form()
        if (form.data.get("api_key") or form.data.get("login")) and not secrets.available():
            messages.error(request, f"Add {secrets.ENV_NAME} to .env first (see the note on this page).")
            return self.render_to_response(self.get_context_data(form=form))
        if not form.is_valid():
            return self.render_to_response(self.get_context_data(form=form))
        adding = self.instance is None
        with transaction.atomic():
            source = form.save(commit=False)
            changed = []
            for field, label in (("api_key", "key"), ("login", "login")):
                value = form.cleaned_data.get(field)
                if value:
                    target = "api_key" if field == "api_key" else "login"
                    setattr(source, f"{target}_encrypted", secrets.encrypt(value))
                    setattr(source, f"{target}_hint", secrets.hint(value))
                    changed.append(f"{label} {getattr(source, f'{target}_hint')}")
            source.updated_by = request.user
            source.save()
            log(
                instance=source,
                action="ai.keyword_source_added" if adding else "ai.keyword_source_changed",
                user=request.user,
                data={"changed": changed, "platform": source.platform},
            )
        verb = "Added" if adding else "Saved"
        extra = (
            ""
            if source.ready or not source.enabled
            else (
                " It isn't asked yet: "
                + ("there's no reader for this platform." if not source.readable else "enter its key.")
            )
        )
        messages.success(request, f"{verb} {source.label}.{extra}")
        return redirect(HOME[0])


class KeywordSourceKeyRemoveView(ConfirmView):
    home = HOME

    def prepare(self, **kwargs):
        self.source = get_object_or_404(KeywordSource, name=kwargs["name"])
        self.page_title = f"Remove the key for {self.source.label}"
        login = " and login" if self.source.login_encrypted else ""
        self.question = f"Remove the stored key{login} for {self.source.label}?"
        self.detail = "The platform stays in the list but isn't asked until you enter a key again."
        self.button = "Remove key"

    def post(self, request, *args, **kwargs):
        source = self.source
        with transaction.atomic():
            source.api_key_encrypted = source.api_key_hint = ""
            source.login_encrypted = source.login_hint = ""
            source.updated_by = request.user
            source.save()
            log(instance=source, action="ai.keyword_source_key_removed", user=request.user)
        messages.success(request, f"Removed the key for {source.label}.")
        return redirect(HOME[0])


class KeywordSourceDeleteView(ConfirmView):
    home = HOME

    def prepare(self, **kwargs):
        self.source = get_object_or_404(KeywordSource, name=kwargs["name"])
        self.page_title = f"Delete {self.source.label}"
        self.question = f"Delete {self.source.label} and its stored key?"
        self.detail = "Search results steps stop asking it. You can add it again later with Add a platform."
        self.button = "Delete platform"

    def post(self, request, *args, **kwargs):
        source = self.source
        with transaction.atomic():
            log(instance=source, action="ai.keyword_source_deleted", user=request.user)
            source.delete()
        messages.success(request, f"Deleted {source.label}.")
        return redirect(HOME[0])
