import re

from django import forms

from apps.ai import catalog

from . import estimates
from .models import BriefPreset, ContentBrief, ContentType, ImageJob
from .pipeline import STEPS, profile_for, steps_for


class BriefForm(forms.ModelForm):
    skeywords_text = forms.CharField(
        label="Secondary keywords",
        required=False,
        help_text="One per line or separated by commas. Each is used once where it fits.",
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    anchors_text = forms.CharField(
        label="Anchors (guest posts)",
        required=False,
        help_text=(
            "One per line as `anchor text | https://product-page`, in the sheet's order. "
            "Each goes in a section on the page's topic; never two in adjacent sections."
        ),
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
            "source_reference",
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
        # A pasted sheet row (initial) wins over the saved brief's values.
        if self.instance.pk and "skeywords_text" not in self.initial:
            self.fields["skeywords_text"].initial = "\n".join(self.instance.skeywords or [])
        if self.instance.pk and "anchors_text" not in self.initial:
            self.fields["anchors_text"].initial = "\n".join(
                f"{a.get('text', '')} | {a.get('url', '')}" for a in (self.instance.anchors or [])
            )

    def clean_skeywords_text(self):
        raw = self.cleaned_data.get("skeywords_text", "")
        return [item.strip() for item in re.split(r"[\n,]", raw) if item.strip()]

    def clean_anchors_text(self):
        anchors = []
        for line in self.cleaned_data.get("anchors_text", "").splitlines():
            if not line.strip():
                continue
            text, sep, url = line.partition("|")
            text, url = text.strip(), url.strip()
            if not sep or not text or not url.startswith(("http://", "https://")):
                raise forms.ValidationError(
                    f"Write each anchor as `anchor text | https://…` (got: {line.strip()[:60]})."
                )
            anchors.append({"text": text, "url": url})
        return anchors

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("content_type") == ContentType.OUTBOUND and not cleaned.get("site_domain"):
            self.add_error("site_domain", "Guest posts need the target site's URL for the site crawl.")
        return cleaned

    def save(self, commit=True):
        self.instance.skeywords = self.cleaned_data.get("skeywords_text", [])
        self.instance.anchors = self.cleaned_data.get("anchors_text", [])
        return super().save(commit)


def parse_step_config(data, content_type):
    """Read the pipeline table from POST data: step_<key>_enabled / _gate / _self_review / _model.

    In autopilot (`mode=autopilot`) every text step self-reviews; a step waits for approval only if its
    box was ticked anyway. The SOP holds a step where it can't pass (docs/sop.md).
    """
    autopilot = data.get("mode") == "autopilot"
    config = {}
    for step_def in steps_for(content_type):
        prefix = f"step_{step_def.key}_"
        model_key = data.get(prefix + "model", "")
        choice = catalog.by_key(model_key) if model_key else None
        config[step_def.key] = {
            "enabled": (prefix + "enabled") in data if step_def.optional else True,
            "gate": (prefix + "gate") in data,
            "self_review": step_def.kind == "text" and (autopilot or (prefix + "self_review") in data),
            "model": model_key if choice and choice.selectable else "",
        }
    return config


def autopilot_config(content_type):
    """Step config for an autopilot run started without the wizard: every text step self-reviews and no
    step waits for approval; the SOP and the marker gate decide where it stops."""
    return {
        step_def.key: {"gate": False, "self_review": step_def.kind == "text"}
        for step_def in steps_for(content_type)
    }


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
        tokens = estimates.step_tokens(key) if step_def.kind == "text" else {}
        rows.append(
            {
                "def": step_def,
                "types": " ".join(types),
                "default": default,
                "groups": catalog.grouped(step_def.kind) if step_def.kind in ("text", "image") else [],
                # For the run estimate (studio.js) and the context guard.
                "tokens": tokens,
                "sop_tokens": estimates.SOP_TOKENS if tokens and not tokens.get("measured") else (0, 0),
                "need": estimates.context_needed(key) if step_def.kind == "text" else 0,
            }
        )
    return rows


class ImageJobForm(forms.ModelForm):
    """The standalone Image generator (apps/studio/imagegen.py)."""

    upload = forms.ImageField(
        label="Or start from your own photo",
        required=False,
        help_text="A licensed photo (yours, Pexels, Unsplash, a stock library). It replaces the generated "
        "one; never upload a watermarked comp.",
    )
    spec_json = forms.CharField(
        label="Infographic content as JSON (optional)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "spellcheck": "false"}),
        help_text="Infographics: leave empty and the model writes it from your description, using only its "
        "facts and figures. Paste a spec to draw exactly that.",
    )

    class Meta:
        model = ImageJob
        fields = [
            "kind",
            "template",
            "headline",
            "description",
            "photo_prompt",
            "region",
            "width",
            "height",
            "corner",
        ]
        widgets = {
            "kind": forms.RadioSelect,
            "description": forms.Textarea(attrs={"rows": 2}),
            "photo_prompt": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {
            "width": "Lead and in-article images. Empty: 1200x630 for a lead image, 1200x675 in an article.",
            "corner": "In-article images: where the logo goes.",
            "description": "Photos: the scene. Infographics: the facts, steps or figures to show, with their "
            "source; every number must be here.",
        }

    def clean(self):
        data = super().clean()
        from .imagegen import ImageJobError, validate_size

        try:
            validate_size(data.get("width"), data.get("height"))
        except ImageJobError as error:
            raise forms.ValidationError(str(error)) from error
        if bool(data.get("width")) != bool(data.get("height")):
            raise forms.ValidationError("Give both a width and a height, or neither.")
        if data.get("kind") == ImageJob.Kind.HERO and not data.get("headline", "").strip():
            self.add_error("headline", "A blog hero needs a headline (the article's H1).")
        if data.get("kind") == ImageJob.Kind.INFOGRAPHIC:
            return self._clean_infographic(data)
        if not (
            data.get("upload") or data.get("description", "").strip() or data.get("photo_prompt", "").strip()
        ):
            raise forms.ValidationError(
                "Describe what the image shows, write a photo prompt, or upload a photo."
            )
        return data

    def _clean_infographic(self, data):
        import json

        if not data.get("template"):
            self.add_error("template", "Choose the infographic's template.")
        raw = (data.get("spec_json") or "").strip()
        data["spec"] = {}
        if raw:
            try:
                data["spec"] = json.loads(raw)
            except json.JSONDecodeError as error:
                self.add_error("spec_json", f"That isn't valid JSON ({error.msg}, line {error.lineno}).")
            else:
                if not isinstance(data["spec"], dict):
                    self.add_error("spec_json", 'The spec is one JSON object: {"title": ..., ...}.')
        elif not data.get("description", "").strip():
            raise forms.ValidationError("Describe what the infographic shows (its facts), or paste a spec.")
        return data


class ImagePlanForm(forms.Form):
    """Pick an existing article for tailored images: a studio run, a published sdsmanager.com article, or
    pasted text."""

    article = forms.ChoiceField(label="Article", required=False)
    url = forms.URLField(
        label="Or a published sdsmanager.com article URL",
        required=False,
        assume_scheme="https",
    )
    text = forms.CharField(
        label="Or paste the article (Markdown)",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )

    def __init__(self, *args, **kwargs):
        from .imagegen import article_choices

        super().__init__(*args, **kwargs)
        self.fields["article"].choices = [("", "Choose an article")] + article_choices()

    def clean(self):
        from .imagegen import ImageJobError, sdsmanager_url

        data = super().clean()
        chosen = [bool(data.get("article")), bool(data.get("url")), bool((data.get("text") or "").strip())]
        if sum(chosen) != 1:
            raise forms.ValidationError("Choose an article, give its URL, or paste it (one of the three).")
        if data.get("url"):
            try:
                data["url"] = sdsmanager_url(data["url"])
            except ImageJobError as error:
                self.add_error("url", str(error))
        return data
