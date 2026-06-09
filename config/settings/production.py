"""
Production Django settings for Social Commerce CRM project.

Use this for production environment.
"""

from config.settings.base import *

DEBUG = env.bool("DEBUG", default=False)

ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["api.socialcommercecrm.com"])

SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 63072000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True

DATABASES = {
    "default": env.db_url("DATABASE_URL"),
}

CELERY_BROKER_URL = env.str("REDIS_URL")
CELERY_RESULT_BACKEND = env.str("REDIS_URL")

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"

CORS_ALLOW_ALL_ORIGINS = False
CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=["https://socialcommercecrm.com"],
)

AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = "hours=1"
AXES_LOCK_OUT_BY_COMBINATION_USER_AND_IP = True

LOGGING["handlers"]["file"]["filename"] = BASE_DIR / "logs" / "production_django.log"
LOGGING["handlers"]["error_file"]["filename"] = BASE_DIR / "logs" / "production_django_error.log"

LOGGING["loggers"]["django"]["level"] = "WARNING"
LOGGING["loggers"]["apps"]["level"] = "WARNING"

REST_FRAMEWORK["DEFAULT_RENDERER_CLASSES"] = [
    "rest_framework.renderers.JSONRenderer",
]
