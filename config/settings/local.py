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
    "outline-kilometer-abroad.ngrok-free.dev",
]

# DATABASES = {
#     "default": env.db_url(
#         "DATABASE_URL", default="postgresql://crm_user:crm_password@localhost:5432/crm_db_dev"
#     ),
# }

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

CELERY_BROKER_URL = env.str("REDIS_URL", default="redis://localhost:6379/1")
CELERY_RESULT_BACKEND = env.str("REDIS_URL", default="redis://localhost:6379/1")

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGINS = []

AXES_FAILURE_LIMIT = 10
AXES_COOLOFF_TIME = 1800

CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[
        "http://localhost:3000",
        "http://localhost:8000",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8003",
        "http://localhost:8003",
    ],
)

# LOGGING["loggers"]["django"]["level"] = "DEBUG"
# LOGGING["loggers"]["apps"]["level"] = "DEBUG"

REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
]

SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 63072000
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False

# CSRF_TRUSTED_ORIGINS: Required for CSRF protection when accessing from different domains/IPs
# Must include the scheme (http:// or https://)
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[
        "http://localhost",
        "http://localhost:8000",
        "http://127.0.0.1",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8003",
        "http://localhost:8003",
        "https://outline-kilometer-abroad.ngrok-free.dev",
    ],
)
