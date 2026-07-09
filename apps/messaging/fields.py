"""
Encrypted model field for storing secrets at rest.

``EncryptedJSONField`` stores arbitrary JSON (e.g. a connected account's
OAuth tokens, app secrets) as symmetrically encrypted (Fernet) text in
the database, while presenting plain Python objects to the application.
The encryption key comes from ``settings.MESSAGING_ENCRYPTION_KEY``.

Design notes:

* Fernet provides authenticated symmetric encryption (AES-128-CBC +
  HMAC-SHA256). Ciphertexts are URL-safe base64, so a ``TextField`` is
  sufficient regardless of payload size.
* The field *looks* like a JSONField to the rest of Django: it accepts
  and returns plain ``dict`` / ``list`` / primitives. Only the on-disk
  representation is encrypted.
* It deconstructs to ``EncryptedJSONField()`` (no constructor args), so
  migrations stay stable and portable. The key never enters the
  migration state, by design.
* On read, if the stored value isn't valid ciphertext (e.g. it predates
  encryption or the key rotated), the field returns the raw value rather
  than raising — this keeps the app usable during key rotation at the
  cost of surfacing plaintext. Rotate keys deliberately.
"""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models


class EncryptionError(RuntimeError):
    """Raised on configuration errors (e.g. missing encryption key)."""


def _get_fernet() -> Fernet:
    """Build a Fernet cipher from ``settings.MESSAGING_ENCRYPTION_KEY``.

    The key must be a valid url-safe base64-encoded 32-byte Fernet key.
    Generate one with::

        from cryptography.fernet import Fernet
        Fernet.generate_key()
    """
    key = getattr(settings, "MESSAGING_ENCRYPTION_KEY", None)
    if not key:
        raise EncryptionError(
            "MESSAGING_ENCRYPTION_KEY is not set. Generate one with "
            "`from cryptography.fernet import Fernet; Fernet.generate_key()` "
            "and set it in your environment."
        )
    if isinstance(key, str):
        key = key.encode()
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:  # pragma: no cover - config error
        raise EncryptionError(
            "MESSAGING_ENCRYPTION_KEY is not a valid Fernet key."
        ) from exc


def encrypt_value(value: Any) -> str:
    """Serialize ``value`` to JSON and return Fernet-encrypted base64 text."""
    if value is None:
        return ""
    raw = json.dumps(value, cls=DjangoJSONEncoder).encode("utf-8")
    return _get_fernet().encrypt(raw).decode("utf-8")


def decrypt_value(text: str) -> Any:
    """Decrypt Fernet text back to a Python object.

    Returns the original (possibly non-encrypted) value if decryption
    fails — see the module docstring for the rationale.
    """
    if not text:
        return None
    try:
        raw = _get_fernet().decrypt(text.encode("utf-8"))
    except InvalidToken:
        # Could be a legacy plaintext value or a key-rotation artifact.
        # Surface it as-is rather than crashing the read path.
        return text
    try:
        return json.loads(raw.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


class EncryptedJSONField(models.TextField):
    """A TextField that transparently encrypts/decrypts JSON values.

    Behaves like a JSONField in Python space (dict/list/scalars in and
    out) but stores Fernet-encrypted base64 text at rest. Use it for
    secrets such as OAuth tokens, app secrets and webhook signing keys.
    """

    description = "Encrypted JSON object stored as Fernet-encrypted text"

    # No constructor arguments so the deconstructed field is portable
    # across machines and never leaks the key into migrations.
    def from_db_value(self, value, expression, connection):  # noqa: D401
        if value is None or value == "":
            return None
        return decrypt_value(value)

    def to_python(self, value):
        if value is None or isinstance(value, (dict, list, int, float, bool)):
            return value
        if isinstance(value, str):
            # A value coming from a form/widget might be encrypted already
            # (from the DB) or a JSON string. Decrypting transparently
            # handles both: invalid ciphertext is returned as-is, and a
            # JSON string decrypts to itself then is parsed below.
            decrypted = decrypt_value(value)
            if isinstance(decrypted, str):
                try:
                    return json.loads(decrypted)
                except (json.JSONDecodeError, ValueError):
                    return decrypted
            return decrypted
        return value

    def get_prep_value(self, value):
        if value is None or value == "":
            return value
        if isinstance(value, str):
            # Assume already-encrypted text from the widget/legacy data;
            # don't double-encrypt.
            return value
        return encrypt_value(value)

    def value_to_string(self, obj):
        """Serialize the field value for serializers (dumpdata, etc.)."""
        return self.value_from_object(obj)
