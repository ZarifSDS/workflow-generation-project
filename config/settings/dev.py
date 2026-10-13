from .base import *  # noqa: F403

DEBUG = True

# Development-only key. Production reads DJANGO_SECRET_KEY from the environment.
SECRET_KEY = os.environ.get(  # noqa: F405
    "DJANGO_SECRET_KEY", "django-insecure-dev-only-change-me-in-production"
)

ALLOWED_HOSTS = ["*"]

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"


try:
    from .local import *  # noqa: F403
except ImportError:
    pass
