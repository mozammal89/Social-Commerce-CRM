"""
Local Django settings for Social Commerce CRM project.

Use this for local development environment.
"""

from config.settings.base import *

DEBUG = True

ALLOWED_HOSTS = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
]

DATABASES = {
    "default": env.db_url(
        "DATABASE_URL", default="postgresql://crm_user:crm_password@localhost:5432/crm_db_dev"
    ),
}

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

CELERY_BROKER_URL = env.str("REDIS_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env.str("REDIS_URL", default="redis://localhost:6379/1")

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGINS = []

AXES_FAILURE_LIMIT = 10
AXES_COOLOFF_TIME = 1800

# LOGGING["loggers"]["django"]["level"] = "DEBUG"
# LOGGING["loggers"]["apps"]["level"] = "DEBUG"

REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]
