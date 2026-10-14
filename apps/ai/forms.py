"""Admin forms for provider keys, added providers and added models (ADR 0008).

Key fields are write-only: they never render a value back, and only the last characters are shown as
a hint elsewhere.
"""

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


class AddedModelForm(forms.ModelForm):
    """Add a model to a provider: pick it from the provider's own list (apps.ai.remote_models) or type its
    id. The name and the free/paid status come from the list when left empty."""

    listed = forms.ChoiceField(label="Model", required=False)

    class Meta:
        model = AddedModel
        fields = ["provider", "model", "label", "status", "typical_seconds"]
        labels = {"model": "Or type a model id", "label": "Name shown in the studio"}
        help_texts = {
            "model": "Only for a model the list doesn't show, exactly as the provider spells it.",
            "label": "Empty: the provider's name for it.",
        }

    def __init__(self, *args, provider_choices=(), remote=(), added=(), default_status="paid", **kwargs):
        super().__init__(*args, **kwargs)
        self.remote = {model.id: model for model in remote}
        self.default_status = default_status
        self.fields["provider"] = forms.ChoiceField(label="Provider", choices=provider_choices)
        self.fields["model"].required = False
        self.fields["label"].required = False
        self.fields["status"] = forms.ChoiceField(
            label="Free or paid",
            required=False,
            choices=[
                (
                    "",
                    f"From the provider's pricing ({AddedModel.Status(default_status).label.lower()} when it "
                    "doesn't say)",
                )
            ]
            + list(AddedModel.Status.choices),
        )
        groups = {"Free": [], "Paid": [], "Price not listed": []}
        for model in remote:
            group = {"free": "Free", "paid": "Paid"}.get(model.status, "Price not listed")
            label = model.option_label + (" · already added" if model.id in added else "")
            groups[group].append((model.id, label))
        self.fields["listed"].choices = [("", "Choose a model")] + [
            (name, options) for name, options in groups.items() if options
        ]
        if not remote:
            self.fields["listed"].widget = forms.HiddenInput()
            self.fields["model"].label = "Model id"
            self.fields["model"].help_text = "Exactly as the provider lists it."

    def clean_model(self):
        model = (self.cleaned_data.get("model") or "").strip()
        if any(char.isspace() for char in model):
            raise forms.ValidationError(
                "Enter the model id exactly as the provider lists it, without spaces."
            )
        return model

    def clean(self):
        data = super().clean()
        typed, picked = data.get("model") or "", data.get("listed") or ""
        if typed and picked and typed != picked:
            raise forms.ValidationError("Pick a model from the list or type one, not both.")
        model_id = typed or picked
        if not model_id:
            raise forms.ValidationError("Pick a model from the list, or type its id.")
        listed = self.remote.get(model_id)
        data["model"] = self.instance.model = model_id
        data["label"] = (data.get("label") or "").strip() or (
            (listed.name or listed.id) if listed else model_id
        )
        data["label"] = data["label"][:80]
        data["status"] = data.get("status") or (
            listed.status if listed and listed.status else self.default_status
        )
        if AddedModel.objects.filter(provider=data.get("provider"), model=model_id).exists():
            raise forms.ValidationError(f"{model_id} is already added for this provider.")
        return data
