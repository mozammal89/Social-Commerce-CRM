"""
Test settings: SQLite in-memory for fast test runs.

Used by pytest via ``DJANGO_SETTINGS_MODULE=config.settings.test``.
"""

from config.settings.base import *  # noqa: F401,F403

DEBUG = False

# Force SQLite for tests (no Postgres needed).
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

# Use locmem cache for tests (avoid Redis dependency).
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "rbac-test-cache",
    },
    "axes_cache": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "rbac-test-axes-cache",
    },
}

# Disable axes for tests (no real auth, no lockout).
MIDDLEWARE = [
    m for m in MIDDLEWARE
    if m != "axes.middleware.AxesMiddleware"
]

# Simpler password hashing for tests.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]
