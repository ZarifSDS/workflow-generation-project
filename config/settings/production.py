from .base import *  # noqa: F403

DEBUG = False

SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]  # noqa: F405
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")  # noqa: F405
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")  # noqa: F405

# Hashed, compressed static files served by WhiteNoise.
STORAGES["staticfiles"]["BACKEND"] = "whitenoise.storage.CompressedManifestStaticFilesStorage"  # noqa: F405

SESSION_COOKIE_SECURE = os.environ.get("DJANGO_SECURE_COOKIES", "false").lower() == "true"  # noqa: F405
CSRF_COOKIE_SECURE = SESSION_COOKIE_SECURE

# Behind Caddy and an HTTPS tunnel or load balancer (docker-compose.share.yml): trust the forwarded
# scheme, so Django builds https:// URLs and the CSRF origin check matches.
if os.environ.get("DJANGO_BEHIND_PROXY", "false").lower() == "true":  # noqa: F405
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Wagtail's live preview shows the page in a same-origin iframe.
X_FRAME_OPTIONS = "SAMEORIGIN"

try:
    from .local import *  # noqa: F403
except ImportError:
    pass
