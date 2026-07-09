"""
Base Django settings for Social Commerce CRM project.

This file contains shared settings across all environments.
"""

import os
from pathlib import Path

from environ import Env

BASE_DIR = Path(__file__).parent.parent.parent
PROJECT_NAME = "social_commerce_crm"
ALLOWED_HOSTS = ["*"]

env = Env()
Env.read_env(os.path.join(BASE_DIR, ".env"))


DEBUG = env.bool("DEBUG", default=False)
SECRET_KEY = env.str("SECRET_KEY", default="django-insecure-dev-key-only-for-development")

DATABASE_URL = env.db_url(
    "DATABASE_URL", default="postgresql://crm_user:crm_password@localhost:5432/crm_db"
)
REDIS_URL = env.str("REDIS_URL", default="redis://localhost:6379/0")


DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "django.contrib.postgres",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework_simplejwt",
    "drf_spectacular",
    "axes",
    "django_celery_beat",
    "corsheaders",
]

LOCAL_APPS = [
    "apps.accounts",
    "apps.stores",
    "apps.common",
    "apps.core",
    "apps.dashboard",
    "apps.permissions",
    "apps.permissions.ui",
    "apps.subscriptions",
    "apps.messaging",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.permissions.middleware.AuditContextMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "axes.middleware.AxesMiddleware",
    "apps.permissions.middleware.HTMX403Middleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.common.context_processors.app_settings",
                "apps.common.context_processors.current_store",
                "apps.common.context_processors.breadcrumbs",
                "apps.permissions.context_processors.rbac",
                "apps.permissions.ui.context_processors.role_permission_breadcrumbs",
                "apps.permissions.ui.context_processors.role_permission_sidebar_extra",
            ],
            "builtins": [
                "django.templatetags.i18n",
                "django.templatetags.static",
                "django.templatetags.cache",
                "apps.permissions.templatetags.rbac",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"


AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {
            "min_length": 8,
        },
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]

AUTHENTICATION_BACKENDS = [
    "axes.backends.AxesStandaloneBackend",
    "django.contrib.auth.backends.ModelBackend",
]


LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True


STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_USER_MODEL = "accounts.User"


# DATABASES = {
#     "default": env.db_url(
#         "DATABASE_URL", default="postgresql://crm_user:crm_password@localhost:5432/crm_db"
#     )
# }

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env.str("DB_NAME", default="crm_db"),
        "USER": env.str("DB_USER", default="your_db_user"),
        "PASSWORD": env.str("DB_PASSWORD", default="password"),
        "HOST": env.str("DB_HOST", default="localhost"),
        "PORT": env.str("DB_PORT", default="5432"),
    }
}


CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": REDIS_URL,
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
        },
    },
    "axes_cache": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    },
}


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework_simplejwt.authentication.JWTAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 20,
    "DEFAULT_FILTER_BACKENDS": [
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        # Form-encoded and multipart parsers are required so browser-driven
        # ``URLSearchParams`` and ``FormData`` POSTs (used by the manage
        # subscription page, the team-management UI, and the stores switch
        # endpoint) reach the view. Without these DRF rejects form-encoded
        # bodies with 415 Unsupported Media Type, even when the serializer
        # fields look identical to the JSON shape the JS is sending.
        "rest_framework.parsers.FormParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "apps.permissions.exception_handler.rbac_exception_handler",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": "timedelta(hours=1)",
    "REFRESH_TOKEN_LIFETIME": "timedelta(days=7)",
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": SECRET_KEY,
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "user_id",
    "AUTH_TOKEN_CLASSES": ("rest_framework_simplejwt.tokens.AccessToken",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Social Commerce CRM API",
    "DESCRIPTION": "A production-ready Social Commerce CRM platform API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "SCHEMA_PATH_PREFIX": "/api/v1",
}


CORS_ALLOWED_ORIGINS = env.list(
    "CORS_ALLOWED_ORIGINS",
    default=[
        "http://localhost:8000",
    ],
)


AXES_FAILURE_LIMIT = 5
AXES_COOLOFF_TIME = 3600
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = "accounts/lockout.html"
AXES_LOCKOUT_URL = "/accounts/lockout/"
AXES_VERBOSE = True


CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = TIME_ZONE
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{levelname} {asctime} {module} {process:d} {thread:d} {message}",
            "style": "{",
        },
        "simple": {
            "format": "{levelname} {asctime} {message}",
            "style": "{",
        },
    },
    'filters': {
        'ignore_chrome_devtools': {
            'class': 'logging.Filter',
            'path': '/.well-known/appspecific/com.chrome.devtools.json',
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
            'filters': ['ignore_chrome_devtools'],
        },
    },
    "root": {
        "handlers": ["console"],
        "level": "INFO",
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.db.backends": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "apps": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
    },
}


SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=False)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=False)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool("SECURE_HSTS_INCLUDE_SUBDOMAINS", default=False)
SECURE_HSTS_PRELOAD = env.bool("SECURE_HSTS_PRELOAD", default=False)
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"
CSRF_COOKIE_HTTPONLY = True
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"

# CSRF_TRUSTED_ORIGINS: Required for CSRF protection when accessing from different domains/IPs
# Must include the scheme (http:// or https://)
CSRF_TRUSTED_ORIGINS = env.list(
    "CSRF_TRUSTED_ORIGINS",
    default=[
        "http://localhost",
    ],
)


EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = env.str("EMAIL_HOST", default="smtp.gmail.com")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_USE_TLS = True
EMAIL_HOST_USER = env.str("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env.str("EMAIL_HOST_PASSWORD", default="")
DEFAULT_FROM_EMAIL = env.str("DEFAULT_FROM_EMAIL", default="noreply@socialcommercecrm.com")


STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}


# ---------------------------------------------------------------------------
# Omnichannel messaging
#
# ``MESSAGING_ENCRYPTION_KEY`` is the Fernet key used by
# ``apps.messaging.fields.EncryptedJSONField`` to encrypt connected-account
# credentials (OAuth tokens, app secrets, webhook signing secrets) at rest.
# Generate a production key with::
#
#     python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
#
# The value below is a throwaway dev key; ALWAYS override it in production
# via the environment so stored credentials are not decryptable with a
# public key. Rotating the key invalidates existing ciphertext (the field
# degrades to surfacing raw text rather than crashing), so rotate
# deliberately and re-connect accounts afterward.
# ---------------------------------------------------------------------------
MESSAGING_ENCRYPTION_KEY = env.str(
    "MESSAGING_ENCRYPTION_KEY",
    default="uTZ5mqfZu7u_aKaPTaIrOAtJGjOE6e-Yc4AC0Y5Zcdc=",
)
