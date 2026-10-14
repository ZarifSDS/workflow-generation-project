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
    """Choose a provider's models: every model it lists is a checkbox, ticked when it is in the model lists,
    so ticking adds and unticking removes (a listed model is hidden, one added by hand deleted). Ids the list
    doesn't show can be typed, one per line. Removals only touch the checkboxes the page showed
    (`shown`), so a post without them never empties the lists."""

    provider = forms.ChoiceField(label="Provider")
    chosen = forms.MultipleChoiceField(label="Models", required=False)
    shown = forms.MultipleChoiceField(required=False, widget=forms.MultipleHiddenInput)
    model = forms.CharField(
        label="Add ids by hand",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="One per line, exactly as the provider spells them: for models its list doesn't show.",
    )
    label = forms.CharField(
        label="Name shown in the studio",
        required=False,
        max_length=80,
        help_text="Only when adding one id by hand. Empty: the id.",
    )
    status = forms.ChoiceField(label="Free or paid, for models added now", required=False)
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
        self, *args, provider_choices=(), remote=(), rows=(), built_in=(), default_status="paid", **kwargs
    ):
        super().__init__(*args, **kwargs)
        self.remote = {model.id: model for model in remote}
        self.rows = {row.model: row for row in rows}
        self.built_in = set(built_in)
        self.default_status = default_status
        self.in_lists = {model_id for model_id, row in self.rows.items() if not row.hidden}
        self.fields["provider"].choices = provider_choices
        self.fields["status"].choices = [
            (
                "",
                f"From the provider's pricing ({AddedModel.Status(default_status).label.lower()} when it "
                "doesn't say)",
            )
        ] + list(AddedModel.Status.choices)
        # Checkboxes: the provider's list (minus the built-in models, always on), then ids added by hand that
        # the list doesn't show (unticking removes them).
        groups = {"Free": [], "Paid": [], "Price not listed": []}
        for model in remote:
            if model.id in self.built_in:
                continue
            group = {"free": "Free", "paid": "Paid"}.get(model.status, "Price not listed")
            groups[group].append((model.id, model.option_label))
        extra = [
            (model_id, f"{row.label} ({model_id})" if row.label != model_id else model_id)
            for model_id, row in sorted(self.rows.items())
            if model_id not in self.remote and not row.hidden
        ]
        if extra:
            groups["In your lists, not in the provider's list" if remote else "In your lists"] = extra
        self.groups = [(name, options) for name, options in groups.items() if options]
        flat = [(model_id, label) for _, options in self.groups for model_id, label in options]
        self.fields["chosen"].choices = flat
        self.fields["shown"].choices = flat
        self.initial.setdefault("chosen", sorted(self.in_lists))
        if not remote:
            self.fields["unlisted_ok"].widget = forms.HiddenInput()

    def checkbox_groups(self):
        """[(group, [(id, label, ticked)])] for the template, with the posted ticks after an error."""
        ticked = set(self.data.getlist("chosen")) if self.is_bound else set(self.initial.get("chosen") or [])
        return [
            (name, [(model_id, label, model_id in ticked) for model_id, label in options])
            for name, options in self.groups
        ]

    def clean_model(self):
        ids = [line.strip() for line in (self.cleaned_data.get("model") or "").splitlines() if line.strip()]
        bad = [model_id for model_id in ids if any(char.isspace() for char in model_id)]
        if bad:
            raise forms.ValidationError(f"Model ids have no spaces: check {', '.join(bad)}.")
        return ids

    def clean(self):
        data = super().clean()
        chosen, shown, typed = (
            set(data.get("chosen") or []),
            set(data.get("shown") or []),
            data.get("model") or [],
        )
        unlisted = [model_id for model_id in typed if self.remote and model_id not in self.remote]
        if unlisted and not data.get("unlisted_ok"):
            # A typed id the provider doesn't list fails at run time (seen: an OpenRouter id filed under
            # local Ollama, and an id missing its "~"). Suggest the nearest listed ids.
            hints = []
            for model_id in unlisted:
                close = difflib.get_close_matches(model_id, list(self.remote), n=3, cutoff=0.6)
                hints.append(f"{model_id} (did you mean {' or '.join(close)}?)" if close else model_id)
            raise forms.ValidationError(
                f"Not in this provider's list of models: {'; '.join(hints)}. Tick it in the list, check the "
                "provider, or tick “Add them anyway” if you're sure."
            )
        already = [model_id for model_id in typed if model_id in self.in_lists or model_id in self.built_in]
        if already:
            raise forms.ValidationError(
                f"Already in the model lists for this provider: {', '.join(already)}."
            )
        self.to_add = [model_id for model_id in [*sorted(chosen), *typed] if model_id not in self.in_lists]
        self.to_add = list(dict.fromkeys(self.to_add))
        self.to_remove = sorted((shown - chosen) & self.in_lists)
        if not self.to_add and not self.to_remove:
            raise forms.ValidationError("Nothing changed: tick or untick models, or type an id.")
        return data

    def save(self):
        """Apply the ticks: (added or restored rows, number removed)."""
        provider = self.cleaned_data["provider"]
        typed = set(self.cleaned_data.get("model") or [])
        label, status = (self.cleaned_data.get("label") or "").strip(), self.cleaned_data.get("status")
        added = []
        for model_id in self.to_add:
            row, listed = self.rows.get(model_id), self.remote.get(model_id)
            if row is not None:  # a hidden model ticked again
                row.hidden = False
                row.save(update_fields=["hidden"])
            else:
                single = len(self.to_add) == 1 and label
                row = AddedModel.objects.create(
                    provider=provider,
                    model=model_id,
                    label=(label if single else (listed.name if listed else "") or model_id)[:80],
                    status=status or (listed.status if listed and listed.status else self.default_status),
                    source=AddedModel.Source.MANUAL
                    if model_id in typed or not listed
                    else AddedModel.Source.LISTED,
                    details=listed.details[:200] if listed else "",
                    typical_seconds=self.cleaned_data.get("typical_seconds"),
                )
            added.append(row)
        removed = 0
        for model_id in self.to_remove:
            row = self.rows[model_id]
            if row.source == AddedModel.Source.LISTED:
                row.hidden = True
                row.save(update_fields=["hidden"])
            else:
                row.delete()
            removed += 1
        return added, removed
