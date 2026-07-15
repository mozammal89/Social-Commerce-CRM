"""
Django system checks for the messaging app.

Currently validates that ``MESSAGING_ENCRYPTION_KEY`` is a proper Fernet
key so a misconfiguration is caught at startup (``manage.py check`` /
``runserver``) rather than causing silent plaintext storage or runtime
crashes during credential read/write.
"""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, register


@register()
def check_encryption_key(app_configs, **kwargs):
    """Verify ``MESSAGING_ENCRYPTION_KEY`` is a valid Fernet key."""
    errors = []

    key = getattr(settings, "MESSAGING_ENCRYPTION_KEY", None)
    if not key:
        errors.append(
            Error(
                "MESSAGING_ENCRYPTION_KEY is not set. Connected-account "
                "credentials cannot be encrypted. Generate a key with: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"',
                id="messaging.E001",
            )
        )
        return errors

    # Validate the key is usable by Fernet.
    try:
        from cryptography.fernet import Fernet

        Fernet(key.encode("utf-8") if isinstance(key, str) else key)
    except Exception as exc:
        errors.append(
            Error(
                f"MESSAGING_ENCRYPTION_KEY is not a valid Fernet key ({exc}). "
                "It must be 44 url-safe base64-encoded characters. Generate a "
                'new one with: python -c "from cryptography.fernet import '
                'Fernet; print(Fernet.generate_key().decode())" and set it in '
                "your .env / environment.",
                id="messaging.E002",
                hint=(
                    "The key currently in use appears malformed. Check your "
                    ".env file for typos, encoding issues, or stray characters."
                ),
            )
        )

    return errors
