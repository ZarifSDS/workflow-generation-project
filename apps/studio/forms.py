import re

from django import forms

from apps.ai import catalog

from .models import BriefPreset, ContentBrief, ContentType
from .pipeline import STEPS, profile_for, steps_for


class BriefForm(forms.ModelForm):
    skeywords_text = forms.CharField(
        label="Secondary keywords",
        required=False,
        help_text="One per line or separated by commas. Each is used once where it fits.",
        widget=forms.Textarea(attrs={"rows": 2}),
    )

    class Meta:
        model = ContentBrief
        fields = [
            "content_type",
            "preset",
            "topic",
            "pkeyword",
            "audience",
            "wordcount",
            "fkgl",
            "region",
            "comprehension",
            "cta_style",
            "site",
            "site_domain",
            "narrative_mode",
            "localise_to",
            "notes",
        ]
        widgets = {
            "content_type": forms.RadioSelect,
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["preset"].required = False
        self.fields["preset"].empty_label = "No preset"
        self.fields["preset"].label = "Start from a preset"
        if self.instance.pk:
            self.fields["skeywords_text"].initial = "\n".join(self.instance.skeywords or [])

    def clean_skeywords_text(self):
        raw = self.cleaned_data.get("skeywords_text", "")
        return [item.strip() for item in re.split(r"[\n,]", raw) if item.strip()]

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("content_type") == ContentType.OUTBOUND and not cleaned.get("site_domain"):
            self.add_error("site_domain", "Guest posts need the target site's URL for the site crawl.")
        return cleaned

    def save(self, commit=True):
        self.instance.skeywords = self.cleaned_data.get("skeywords_text", [])
        return super().save(commit)


def parse_step_config(data, content_type):
    """Read the pipeline table from POST data: step_<key>_enabled / _gate / _model."""
    config = {}
    for step_def in steps_for(content_type):
        prefix = f"step_{step_def.key}_"
        model_key = data.get(prefix + "model", "")
        choice = catalog.by_key(model_key) if model_key else None
        config[step_def.key] = {
            "enabled": (prefix + "enabled") in data if step_def.optional else True,
            "gate": (prefix + "gate") in data,
            "model": model_key if choice and choice.selectable else "",
        }
    return config


def preset_from_brief(name, brief_data, step_config):
    """Create or update a preset from the wizard's current values."""
    fields = [
        "content_type",
        "region",
        "fkgl",
        "wordcount",
        "audience",
        "comprehension",
        "cta_style",
        "narrative_mode",
    ]
    defaults = {field: brief_data.get(field) for field in fields if brief_data.get(field) not in (None, "")}
    defaults["step_models"] = {key: cfg["model"] for key, cfg in step_config.items() if cfg.get("model")}
    preset, _ = BriefPreset.objects.update_or_create(name=name, defaults=defaults)
    return preset


def step_rows(content_type, preset=None, existing=None):
    """Rows for the wizard's pipeline table across all content types (JS shows the right ones)."""
    rows = []
    for key, step_def in STEPS.items():
        types = [t for t in ContentType.values if key in [s.key for s in steps_for(t)]]
        profile = profile_for(key) if step_def.profile else {}
        default = f"{profile['provider']}::{profile['model']}" if profile.get("provider") else ""
        if preset and preset.step_models.get(key):
            default = preset.step_models[key]
        rows.append(
            {
                "def": step_def,
                "types": " ".join(types),
                "default": default,
                "groups": catalog.grouped(step_def.kind) if step_def.kind in ("text", "image") else [],
            }
        )
    return rows
