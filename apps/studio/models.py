from django.conf import settings
from django.db import models
from django.utils import timezone

from .permissions import PERMISSIONS
from .pipeline import STEPS

VERSIONS_TO_KEEP = 3  # the first version is always kept as well (docs/ux.md)


class ContentType(models.TextChoices):
    SEO_BLOG = "seo_blog", "SEO blog"
    OUTBOUND = "outbound", "Guest post"
    LEAD_MAGNET = "lead_magnet", "Lead magnet"
    WHITEPAPER = "whitepaper", "Whitepaper"


class Region(models.TextChoices):
    US = "US", "US (OSHA, US spelling)"
    UK = "UK", "UK (HSE, COSHH, GB CLP)"
    AU = "AU", "Australia (Safe Work Australia)"
    CA = "CA", "Canada (WHMIS)"
    NZ = "NZ", "New Zealand (WorkSafe)"
    EU = "EU", "EU (REACH, CLP)"


class Comprehension(models.TextChoices):
    BEGINNER = "beginner", "Beginner"
    PRACTITIONER = "practitioner", "Practitioner"
    EXPERT = "expert", "Expert"


class CTAStyle(models.TextChoices):
    SUBTLE = "subtle", "Subtle (one in-sentence link)"
    BUTTON = "button", "Button"
    NONE = "none", "None"


class NarrativeMode(models.TextChoices):
    INFORMATIONAL = "informational", "Informational"
    PERSONAL = "personal", "Personal"


class BriefFieldsMixin(models.Model):
    """Fields shared by briefs and presets."""

    content_type = models.CharField(max_length=20, choices=ContentType.choices, default=ContentType.SEO_BLOG)
    region = models.CharField(max_length=4, choices=Region.choices, default=Region.US)
    fkgl = models.DecimalField(
        "Reading grade (FKGL)",
        max_digits=4,
        decimal_places=1,
        default=9,
        help_text="Soft target, checked per section in Review and edit.",
    )
    wordcount = models.PositiveIntegerField(
        "Target length (words)", null=True, blank=True, help_text="A guide, not a quota."
    )
    audience = models.CharField(max_length=255, blank=True)
    comprehension = models.CharField(
        "Reader's expertise", max_length=20, choices=Comprehension.choices, default=Comprehension.PRACTITIONER
    )
    cta_style = models.CharField(
        "Call to action", max_length=10, choices=CTAStyle.choices, default=CTAStyle.SUBTLE
    )
    narrative_mode = models.CharField(
        max_length=20,
        choices=NarrativeMode.choices,
        blank=True,
        help_text="Guest posts only. The site crawl proposes this.",
    )

    class Meta:
        abstract = True


class BriefPreset(BriefFieldsMixin):
    name = models.CharField(max_length=120, unique=True)
    step_models = models.JSONField(
        default=dict, blank=True, help_text='Model per step, e.g. {"draft": "ollama::model"}.'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ContentBrief(BriefFieldsMixin):
    topic = models.CharField(max_length=255)
    pkeyword = models.CharField(
        "Primary keyword",
        max_length=120,
        help_text="Goes in the title, the first 100 words and 2–3 headings.",
    )
    skeywords = models.JSONField("Secondary keywords", default=list, blank=True)
    site = models.CharField("Target site", max_length=255, blank=True, help_text="Guest posts only.")
    site_domain = models.URLField("Target site URL", blank=True, help_text="Guest posts only.")
    notes = models.TextField(blank=True)
    localise_to = models.CharField(
        "Localise to",
        max_length=4,
        choices=Region.choices,
        blank=True,
        help_text="Used by the optional Localise step: the region of the variant to produce.",
    )
    preset = models.ForeignKey(
        BriefPreset, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return self.topic

    def as_prompt_dict(self):
        """Shape used by the prompts and metrics (same keys as eval/briefs.yaml)."""
        return {
            "id": f"brief-{self.pk}",
            "type": self.content_type,
            "topic": self.topic,
            "pkeyword": self.pkeyword,
            "skeywords": list(self.skeywords or []),
            "wordcount": self.wordcount,
            "fkgl": float(self.fkgl),
            "audience": self.audience,
            "comprehension": self.comprehension,
            "region": self.region,
            "cta_style": self.cta_style,
            "site": self.site,
            "narrative_mode": self.narrative_mode,
            "notes": self.notes,
        }


class GenerationRun(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        NEEDS_REVIEW = "needs_review", "Needs your review"
        DONE = "done", "Done"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"

    brief = models.ForeignKey(ContentBrief, on_delete=models.CASCADE, related_name="runs")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.QUEUED)
    reject_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        # Studio-wide permissions (apps/studio/permissions.py); kept on the run model by convention.
        permissions = PERMISSIONS

    def __str__(self):
        return f"{self.brief.topic} (run {self.pk})"

    @property
    def enabled_steps(self):
        return self.steps.filter(enabled=True)

    @property
    def current_step(self):
        """The step that needs attention: ready, running, queued or failed; else the last approved."""
        steps = list(self.enabled_steps)
        for status in (
            StepRun.Status.READY,
            StepRun.Status.REJECTED,
            StepRun.Status.FAILED,
            StepRun.Status.RUNNING,
            StepRun.Status.QUEUED,
        ):
            for step in steps:
                if step.status == status:
                    return step
        return steps[-1] if steps else None


class StepRun(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Waiting"
        QUEUED = "queued", "Queued"
        RUNNING = "running", "Running"
        READY = "ready", "Ready for review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Skipped"

    run = models.ForeignKey(GenerationRun, on_delete=models.CASCADE, related_name="steps")
    key = models.CharField(max_length=30)
    order = models.PositiveSmallIntegerField()
    enabled = models.BooleanField(default=True)
    gate = models.BooleanField("Wait for my approval", default=True)
    provider = models.CharField(max_length=30, blank=True)
    model = models.CharField(max_length=200, blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    error = models.TextField(blank=True)
    regenerate_note = models.TextField(blank=True)
    notified_at = models.DateTimeField(null=True, blank=True)  # "ready for review" message shown
    queued_at = models.DateTimeField(null=True, blank=True)  # handed to the worker (services.enqueue)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["run", "order"]
        constraints = [models.UniqueConstraint(fields=["run", "key"], name="unique_step_per_run")]

    def __str__(self):
        return f"{self.label} ({self.get_status_display()})"

    @property
    def definition(self):
        return STEPS[self.key]

    @property
    def label(self):
        return self.definition.label

    @property
    def latest_version(self):
        return self.versions.order_by("-number").first()

    @property
    def timer_since(self):
        """When the live timer starts: the start of a running step, or when a queued step was queued."""
        if self.status == self.Status.RUNNING:
            return self.started_at
        if self.status == self.Status.QUEUED:
            return self.queued_at
        return None

    @property
    def elapsed_seconds(self):
        since = self.timer_since
        return max(0, round((timezone.now() - since).total_seconds())) if since else None

    @property
    def duration_seconds(self):
        """How long the last run of the step took (finished, failed or waiting for review)."""
        finished = (self.Status.READY, self.Status.APPROVED, self.Status.FAILED, self.Status.REJECTED)
        if self.status not in finished or not (self.started_at and self.finished_at):
            return None
        return max(0, round((self.finished_at - self.started_at).total_seconds()))


class StepVersion(models.Model):
    class Source(models.TextChoices):
        AI = "ai", "Generated"
        EDIT = "edit", "Your edit"

    step = models.ForeignKey(StepRun, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField()
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.AI)
    provider = models.CharField(max_length=30, blank=True)
    model = models.CharField(max_length=200, blank=True)
    content = models.TextField(blank=True)
    image = models.ForeignKey(
        "wagtailimages.Image", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    metrics = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["step", "number"]
        constraints = [models.UniqueConstraint(fields=["step", "number"], name="unique_version_number")]

    def __str__(self):
        return f"v{self.number}"


class MetadataOption(models.Model):
    class Kind(models.TextChoices):
        TITLE = "title", "Title"
        META = "meta", "Meta description"
        SLUG = "slug", "URL slug"
        TAGS = "tags", "Tags"
        EXCERPT = "excerpt", "Excerpt"

    # Character limits shown in the editor (the skill: meta titles 40-60, descriptions 150-160).
    LIMITS = {"title": 60, "meta": 160, "slug": 75, "tags": 300, "excerpt": 400}

    run = models.ForeignKey(GenerationRun, on_delete=models.CASCADE, related_name="metadata_options")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    text = models.CharField(max_length=500)
    source = models.CharField(
        max_length=10, choices=StepVersion.Source.choices, default=StepVersion.Source.AI
    )
    selected = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["run", "kind", "created_at"]

    def __str__(self):
        return self.text

    @property
    def limit(self):
        return self.LIMITS[self.kind]

    @property
    def too_long(self):
        return len(self.text) > self.limit


class AudienceProfile(models.Model):
    """Who we write for in one region (Settings › Audience profiles). Every prompt and the suggestions chat
    get it; new briefs take their audience and reading grade from it."""

    region = models.CharField(max_length=4, choices=Region.choices, unique=True)
    audience = models.CharField(
        max_length=255,
        help_text=(
            "Who reads the articles, e.g. EHS managers at mid-sized UK manufacturers evaluating software."
        ),
    )
    reading_grade = models.DecimalField(
        "target reading grade (FKGL)",
        max_digits=4,
        decimal_places=1,
        default=8,
        help_text="Applied per section (H2, and H3 in long sections) in Review and edit.",
    )
    style = models.TextField(
        blank=True,
        help_text="How to write for them: tone, spelling, terms to use or avoid, what they care about.",
    )
    ranking_notes = models.TextField(
        blank=True,
        help_text=(
            "What tends to rank for this market, e.g. 'answer first, short how-to steps, an FAQ, UK sources'."
        ),
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["region"]

    def __str__(self):
        return f"{self.get_region_display()}: {self.audience}"

    def prompt_block(self):
        lines = [
            f"Audience for {self.get_region_display()}: {self.audience}.",
            f"Target reading grade: FKGL {self.reading_grade:g} in every section.",
        ]
        if self.style.strip():
            lines.append(f"How to write for them: {' '.join(self.style.split())}")
        if self.ranking_notes.strip():
            lines.append(f"What ranks in this market: {' '.join(self.ranking_notes.split())}")
        return "\n".join(lines)


class ChatMessage(models.Model):
    """The suggestions chat on a step (apps/studio/assistant.py): your requests and the model's replies.

    An assistant message is created pending and filled in by the worker. "apply" and "tune" replies save a
    new version of the step's output; "suggest" replies only answer.
    """

    class Role(models.TextChoices):
        USER = "user", "You"
        ASSISTANT = "assistant", "Assistant"

    class Action(models.TextChoices):
        SUGGEST = "suggest", "Suggestions"
        APPLY = "apply", "Apply as new version"
        TUNE = "tune", "Tune a section's reading grade"

    class Status(models.TextChoices):
        PENDING = "pending", "Waiting"
        RUNNING = "running", "Working"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    step = models.ForeignKey(StepRun, on_delete=models.CASCADE, related_name="chat")
    role = models.CharField(max_length=10, choices=Role.choices)
    action = models.CharField(max_length=10, choices=Action.choices, default=Action.SUGGEST)
    content = models.TextField(blank=True)
    payload = models.JSONField(default=dict, blank=True)  # tune: {"index", "target", "name"}; base version
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DONE)
    version_number = models.PositiveIntegerField(null=True, blank=True)  # version an apply/tune saved
    provider = models.CharField(max_length=30, blank=True)
    model = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "pk"]

    def __str__(self):
        return f"{self.get_role_display()}: {self.content[:40]}"

    @property
    def is_open(self):
        return self.status in (self.Status.PENDING, self.Status.RUNNING)

    @property
    def duration_seconds(self):
        if self.started_at and self.finished_at:
            return max(0, round((self.finished_at - self.started_at).total_seconds()))
        return None
