from .dev import *  # noqa: F403

# Run tasks inline so tests don't need the worker container.
TASKS = {"default": {"BACKEND": "django.tasks.backends.immediate.ImmediateBackend"}}

# Wagtail caches site lookups; a real cache would leak state between tests
# after their database changes roll back.
CACHES = {"default": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"}}

# Tests run executors explicitly with fake providers.
STUDIO_EXECUTE_STEPS = False
STUDIO_CRAWL_PACE_SECONDS = 0
STUDIO_QUALITY_SCANS = False  # subprocess scans are covered by their own tests

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
