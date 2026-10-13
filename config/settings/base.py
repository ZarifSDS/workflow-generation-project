"""
Base settings shared by every environment.

Values that differ per machine or contain secrets come from environment
variables (see .env.example). Never hard-code secrets here.
"""

import os
from datetime import timedelta
from pathlib import Path

import dj_database_url

PROJECT_DIR = Path(__file__).resolve().parent.parent
BASE_DIR = PROJECT_DIR.parent


def env_list(name, default=""):
    return [item.strip() for item in os.environ.get(name, default).split(",") if item.strip()]


# Application definition

INSTALLED_APPS = [
    "apps.home",
    "apps.search",
    "apps.studio",
    "apps.ai",
    "apps.content",
    "apps.brand",  # admin theme (palette, typography)
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail.contrib.settings",
    "wagtail.contrib.table_block",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail",
    "modelcluster",
    "taggit",
    "django_filters",
    "django_tasks_db",
    "axes",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    # Required by Wagtail's database search backend on Postgres (Django 6.1 system check postgres.E005).
    "django.contrib.postgres",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "wagtail.contrib.redirects.middleware.RedirectMiddleware",
    "apps.studio.middleware.ReviewNotificationsMiddleware",
    # Keep last: turns failed-login lockouts into the lockout page.
    "axes.middleware.AxesMiddleware",
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]

# Login rate limiting (django-axes, M8): 5 failed attempts for one username from one address lock that
# combination for 15 minutes. Combining both keeps one person's typos from locking out a team that shares
# an address behind a proxy or tunnel. Unlock early: `python manage.py axes_reset_username <name>`.
AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = timedelta(minutes=15)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "account_locked.html"
# Behind Caddy (share or production mode) the client address is the one before the last proxy hop.
AXES_IPWARE_PROXY_COUNT = int(os.environ.get("DJANGO_PROXY_COUNT", "0")) or None
AXES_IPWARE_META_PRECEDENCE_ORDER = (
    ["HTTP_X_FORWARDED_FOR", "REMOTE_ADDR"] if AXES_IPWARE_PROXY_COUNT else ["REMOTE_ADDR"]
)

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [PROJECT_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "wagtail.contrib.settings.context_processors.settings",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# Database: Postgres in Docker (DATABASE_URL); SQLite fallback for quick local checks.

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}",
        conn_max_age=600,
        conn_health_checks=True,
    )
}


# Background tasks: Django's task framework with a database-backed queue.
# The `worker` container runs `python manage.py db_worker`.

TASKS = {
    "default": {
        "BACKEND": "django_tasks_db.DatabaseBackend",
    }
}


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    # The admin login can be on the internet (share and production modes): 12 characters minimum.
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalization

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.environ.get("TIME_ZONE", "Asia/Dhaka")
USE_I18N = True
USE_TZ = True


# Static and media files

STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]
STATICFILES_DIRS = [PROJECT_DIR / "static"]
STATIC_ROOT = BASE_DIR / "static"
STATIC_URL = "/static/"
MEDIA_ROOT = Path(os.environ.get("MEDIA_ROOT", BASE_DIR / "media"))
MEDIA_URL = "/media/"

STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}

DATA_UPLOAD_MAX_NUMBER_FIELDS = 10_000


# Wagtail

WAGTAIL_SITE_NAME = "Content Workflow Studio"
WAGTAILSEARCH_BACKENDS = {"default": {"BACKEND": "wagtail.search.backends.database"}}
WAGTAILADMIN_BASE_URL = os.environ.get("WAGTAILADMIN_BASE_URL", "http://localhost:8000")
WAGTAILDOCS_EXTENSIONS = ["csv", "docx", "key", "odt", "pdf", "pptx", "rtf", "txt", "xlsx", "zip"]
# Upload limits (user decision 2026-10-13): 10 MB per image, 25 MB per document (sized for PDFs).
# Wagtail has one limit for all document types. The proxies allow a little more for form overhead.
WAGTAILIMAGES_MAX_UPLOAD_SIZE = 10 * 1024 * 1024
WAGTAILDOCS_MAX_UPLOAD_SIZE = 25 * 1024 * 1024


# AI providers: base URLs only. API keys are read from the environment by the
# provider layer at call time and are never stored in the database.

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://host.docker.internal:11434")
COMFYUI_BASE_URL = os.environ.get("COMFYUI_BASE_URL", "http://host.docker.internal:8188")
# Workflows exported from ComfyUI in API format; the catalog names them by file (docs/setup.md).
COMFYUI_WORKFLOWS_DIR = BASE_DIR / "comfyui" / "workflows"

# Some provider edges (e.g. Groq) reject requests without a real User-Agent.
AI_USER_AGENT = "workflow-studio/0.1 (+https://github.com/ZarifSDS/workflow-generation-project)"

# Free providers verified 2026-10-13 (docs/providers.md).
AI_PROVIDERS = {
    "ollama": {"adapter": "ollama_native", "base_url": OLLAMA_BASE_URL},
    "ollama_cloud": {
        "adapter": "openai_compat",
        "base_url": "https://ollama.com/v1",
        "api_key_env": "OLLAMA_CLOUD_API_KEY",
    },
    "gemini": {
        "adapter": "openai_compat",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GEMINI_API_KEY",
    },
    "groq": {
        "adapter": "openai_compat",
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
    },
    "comfyui": {"adapter": "comfyui", "base_url": COMFYUI_BASE_URL},
    "cloudflare": {
        "adapter": "cloudflare_images",
        "base_url": "https://api.cloudflare.com/client/v4",
        "api_key_env": "CLOUDFLARE_API_TOKEN",
        "account_env": "CLOUDFLARE_ACCOUNT_ID",
    },
}

# Profiles map pipeline steps to a provider and model.
# INTERIM defaults so the UI has a sensible preselection; they are replaced by the
# evaluation results (docs/model-eval.md). Every step can override them per run.
# Shape: {"quality": {"provider": ..., "model": ..., "options": {...}, "fallback": {...}}}
AI_PROFILES = {
    "quality": {
        "provider": "ollama",
        "model": "huihui_ai/Qwen3.8-abliterated:latest",
        "options": {"num_ctx": 32768, "think": True},
        "fallback": {"provider": "ollama_cloud", "model": "gpt-oss:120b"},
    },
    "fast": {
        "provider": "ollama_cloud",
        "model": "gpt-oss:120b",
        "fallback": {"provider": "groq", "model": "openai/gpt-oss-120b"},
    },
    # The review sequence makes 5-8 calls, so a fast model is the interim default here;
    # the M5 edit round decides the real one.
    "edit": {
        "provider": "ollama_cloud",
        "model": "gpt-oss:120b",
        "fallback": {"provider": "groq", "model": "openai/gpt-oss-120b"},
    },
    "image": {
        "provider": "cloudflare",
        "model": "@cf/black-forest-labs/flux-2-klein-4b",
        # The hero layout (sds-hero-stock) is 1440x810; 816 keeps the height a multiple of 16.
        "options": {"width": 1440, "height": 816},
        "fallback": {"provider": "cloudflare", "model": "@cf/black-forest-labs/flux-1-schnell"},
    },
    # Looks at the generated hero photo: subject box, facing, readable text, safety problems.
    "vision": {
        "provider": "gemini",
        "model": "gemini-3.7-flash",
        "options": {"temperature": 0},
        "fallback": {
            "provider": "ollama",
            "model": "qwen3-vl:8b-instruct",
            "options": {"num_ctx": 8192, "temperature": 0},
        },
    },
}
AI_PROFILES_INTERIM = True  # flips to False once docs/model-eval.md records the chosen defaults

# Content Studio pipeline execution (the worker container runs queued steps).
STUDIO_EXECUTE_STEPS = True
STUDIO_CRAWL_MAX_PAGES = 8
STUDIO_CRAWL_PACE_SECONDS = 5
# Optional: the Publish step POSTs the saved draft here (e.g. an n8n Webhook node; docs/workflow.md).
# With a secret, requests carry X-Studio-Signature: sha256=<HMAC of the body>.
STUDIO_PUBLISH_WEBHOOK_URL = os.environ.get("STUDIO_PUBLISH_WEBHOOK_URL", "")
STUDIO_WEBHOOK_SECRET = os.environ.get("STUDIO_WEBHOOK_SECRET", "")

AI_RETRIES = 3
AI_RETRY_BACKOFF = 5  # seconds; grows 5, 15, 45


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"redact_secrets": {"()": "apps.ai.redact.RedactingFilter"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "filters": ["redact_secrets"]}},
    "root": {"handlers": ["console"], "level": os.environ.get("LOG_LEVEL", "INFO")},
    # httpx logs every request URL at INFO, which would print account IDs.
    "loggers": {
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
        "openai": {"level": "WARNING"},
        "httpx2": {"level": "WARNING"},  # the openai SDK's bundled httpx fork
    },
}
