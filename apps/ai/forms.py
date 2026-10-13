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
    class Meta:
        model = AddedModel
        fields = ["provider", "model", "label", "status", "typical_seconds"]
        labels = {"model": "Model id", "label": "Name shown in the studio"}

    def __init__(self, *args, provider_choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["provider"] = forms.ChoiceField(label="Provider", choices=provider_choices)

    def clean_model(self):
        model = self.cleaned_data["model"].strip()
        if not model or any(char.isspace() for char in model):
            raise forms.ValidationError(
                "Enter the model id exactly as the provider lists it, without spaces."
            )
        return model
