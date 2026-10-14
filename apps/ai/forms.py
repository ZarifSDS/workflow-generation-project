"""Admin forms for provider keys, added providers and added models (ADR 0008).

Key fields are write-only: they never render a value back, and only the last characters are shown as
a hint elsewhere.
"""

import difflib
from urllib.parse import urlsplit

from django import forms
from django.conf import settings

from .models import AddedModel, ProviderConfig

# Plain http is allowed only for services on this machine or the Docker host.
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}


def _key_field(label, required):
    return forms.CharField(
        label=label,
        required=required,
        strip=True,
        max_length=500,
        widget=forms.PasswordInput(
            render_value=False,
            attrs={"autocomplete": "new-password", "spellcheck": "false", "autocapitalize": "off"},
        ),
    )


def _clean_secret(value, what):
    if value and (len(value) < 8 or any(char.isspace() for char in value)):
        raise forms.ValidationError(f"That doesn't look like a {what}: no spaces, at least 8 characters.")
    return value


class KeyForm(forms.Form):
    """Set or replace the key of a provider. Empty fields leave the stored value as it is."""

    api_key = _key_field("API key", required=False)

    def __init__(self, *args, needs_account=False, required=False, account_label="Account ID", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["api_key"].required = required
        if needs_account:
            self.fields["account_id"] = _key_field(account_label, required=False)

    def clean_api_key(self):
        return _clean_secret(self.cleaned_data.get("api_key", ""), "key")

    def clean_account_id(self):
        return _clean_secret(self.cleaned_data.get("account_id", ""), "account ID")

    def clean(self):
        data = super().clean()
        if not self.errors and not data.get("api_key") and not data.get("account_id"):
            raise forms.ValidationError("Enter a key to save, or go back.")
        return data


class AddedProviderForm(forms.ModelForm):
    """An OpenAI-compatible provider such as OpenRouter."""

    api_key = _key_field("API key", required=False)

    class Meta:
        model = ProviderConfig
        fields = ["label", "name", "base_url"]
        labels = {"name": "Short id", "base_url": "API address (OpenAI-compatible)"}
        help_texts = {
            "name": "Lowercase letters, digits and hyphens, e.g. openrouter",
            "base_url": "e.g. https://openrouter.ai/api/v1",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        editing = self.instance.pk is not None
        self.fields["api_key"].required = not editing
        if editing:
            self.fields["name"].disabled = True
            self.fields["api_key"].help_text = (
                "Leave empty to keep the stored key. Changing the address without entering the key again "
                "removes the stored key, so a key is never sent to an address it wasn't entered for."
            )

    def clean_name(self):
        name = self.cleaned_data["name"]
        if not self.instance.pk and name in settings.AI_PROVIDERS:
            raise forms.ValidationError("That id belongs to a built-in provider; set its key from the list.")
        return name

    def clean_base_url(self):
        url = self.cleaned_data["base_url"].strip().rstrip("/")
        parts = urlsplit(url)
        if parts.username or parts.password or parts.query or parts.fragment:
            raise forms.ValidationError("Use the plain API address, without a login, query or #fragment.")
        if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in LOCAL_HOSTS):
            raise forms.ValidationError("Use https (plain http only for services on this machine).")
        return url

    def clean_api_key(self):
        return _clean_secret(self.cleaned_data.get("api_key", ""), "key")


class AddedModelForm(forms.Form):
    """Add one or more models to a provider: pick them from the provider's own list (apps.ai.remote_models)
    or type their ids, one per line. A name and the free/paid status come from the list when left empty;
    a hidden model that is picked again is restored."""

    provider = forms.ChoiceField(label="Provider")
    listed = forms.MultipleChoiceField(
        label="Models",
        required=False,
        widget=forms.SelectMultiple(attrs={"size": 14}),
        help_text="Ctrl-click (Cmd-click on a Mac) to pick several.",
    )
    model = forms.CharField(
        label="Or type model ids",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="One per line, exactly as the provider spells them. For models the list doesn't show.",
    )
    label = forms.CharField(
        label="Name shown in the studio",
        required=False,
        max_length=80,
        help_text="Only when adding one model. Empty: the provider's name for it.",
    )
    status = forms.ChoiceField(label="Free or paid", required=False)
    typical_seconds = forms.IntegerField(
        label="Typical seconds per step",
        required=False,
        min_value=1,
        help_text="Optional, shown next to the model.",
    )
    unlisted_ok = forms.BooleanField(
        label="Add them anyway",
        required=False,
        help_text="Only when you're sure: the provider's list doesn't show these ids.",
    )

    def __init__(
        self, *args, provider_choices=(), remote=(), added=(), hidden=(), default_status="paid", **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.remote = {model.id: model for model in remote}
        self.added, self.hidden = set(added), set(hidden)
        self.default_status = default_status
        self.items = []
        self.fields["provider"].choices = provider_choices
        self.fields["status"].choices = [
            (
                "",
                f"From the provider's pricing ({AddedModel.Status(default_status).label.lower()} when it "
                "doesn't say)",
            )
        ] + list(AddedModel.Status.choices)
        groups = {
            "Free": [],
            "Paid": [],
            "Price not listed": [],
            "Hidden (picking restores them)": [],
            "Already in the lists": [],
        }
        for model in remote:
            if model.id in self.added:
                group = "Already in the lists"
            elif model.id in self.hidden:
                group = "Hidden (picking restores them)"
            else:
                group = {"free": "Free", "paid": "Paid"}.get(model.status, "Price not listed")
            groups[group].append((model.id, model.option_label))
        self.fields["listed"].choices = [(name, options) for name, options in groups.items() if options]
        if not remote:
            self.fields["listed"].widget = forms.MultipleHiddenInput()
            self.fields["unlisted_ok"].widget = forms.HiddenInput()
            self.fields["model"].label = "Model ids"

    def clean_model(self):
        ids = [line.strip() for line in (self.cleaned_data.get("model") or "").splitlines() if line.strip()]
        bad = [model_id for model_id in ids if any(char.isspace() for char in model_id)]
        if bad:
            raise forms.ValidationError(f"Model ids have no spaces: check {', '.join(bad)}.")
        return ids

    def clean(self):
        data = super().clean()
        typed, picked = data.get("model") or [], data.get("listed") or []
        ids = list(dict.fromkeys([*picked, *typed]))
        if not ids:
            raise forms.ValidationError("Pick a model from the list, or type its id.")
        unlisted = [model_id for model_id in typed if self.remote and model_id not in self.remote]
        if unlisted and not data.get("unlisted_ok"):
            # A typed id the provider doesn't list fails at run time (seen: an OpenRouter id filed under
            # local Ollama, and an id missing its "~"). Suggest the nearest listed ids.
            hints = []
            for model_id in unlisted:
                close = difflib.get_close_matches(model_id, list(self.remote), n=3, cutoff=0.6)
                hints.append(f"{model_id} (did you mean {' or '.join(close)}?)" if close else model_id)
            raise forms.ValidationError(
                f"Not in this provider's list of models: {'; '.join(hints)}. Pick from the list, check the "
                "provider, or tick “Add them anyway” if you're sure."
            )
        existing = {
            row.model: row for row in AddedModel.objects.filter(provider=data.get("provider"), model__in=ids)
        }
        already = [model_id for model_id in ids if model_id in existing and not existing[model_id].hidden]
        if already:
            raise forms.ValidationError(
                f"Already in the model lists for this provider: {', '.join(already)}."
            )
        label = (data.get("label") or "").strip()
        self.items = []
        for model_id in ids:
            listed = self.remote.get(model_id)
            self.items.append(
                {
                    "model": model_id,
                    "row": existing.get(model_id),
                    "label": (
                        label if len(ids) == 1 and label else (listed.name if listed else "") or model_id
                    )[:80],
                    "status": data.get("status")
                    or (listed.status if listed and listed.status else self.default_status),
                    "details": listed.details[:200] if listed else "",
                }
            )
        return data

    def save(self):
        """Create the new rows and restore hidden ones; returns them."""
        rows = []
        provider, seconds = self.cleaned_data["provider"], self.cleaned_data.get("typical_seconds")
        for item in self.items:
            row = item["row"]
            if row is not None:  # a hidden model picked again
                row.hidden = False
                row.save(update_fields=["hidden"])
            else:
                row = AddedModel.objects.create(
                    provider=provider,
                    model=item["model"],
                    label=item["label"],
                    status=item["status"],
                    details=item["details"],
                    typical_seconds=seconds,
                )
            rows.append(row)
        return rows
