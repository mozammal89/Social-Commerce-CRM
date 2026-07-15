"""
Encrypted model field for storing secrets at rest.

``EncryptedJSONField`` stores arbitrary JSON (e.g. a connected account's
OAuth tokens, app secrets) as symmetrically encrypted (Fernet) text in
the database, while presenting plain Python objects to the application.
The encryption key comes from ``settings.MESSAGING_ENCRYPTION_KEY``.

Design notes
------------
* Fernet provides authenticated symmetric encryption (AES-128-CBC +
  HMAC-SHA256). Ciphertexts are URL-safe base64, so a ``TextField`` is
  sufficient regardless of payload size.
* The field *looks* like a JSONField to the rest of Django: it accepts
  and returns plain ``dict`` / ``list`` / primitives. Only the on-disk
  representation is encrypted.
* It deconstructs to ``EncryptedJSONField()`` (no constructor args), so
  migrations stay stable and portable. The key never enters the
  migration state, by design.
* On read, if the stored value can't be decrypted (wrong key, legacy
  plaintext, or a misconfigured key) the field returns the raw value
  rather than crashing — this keeps the app running while the developer
  fixes the configuration. A Django system check flags a bad key at
  startup.
* On write, a misconfigured key is a **hard error**: the save fails
  rather than silently persisting plaintext. This is deliberate —
  silently storing secrets as plaintext is a far worse failure mode
  than a crashed save.
"""

from __future__ import annotations

import ast
import json
import logging
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

logger = logging.getLogger(__name__)

# Module-level cache for the Fernet cipher. Built once on first use and
# reused for every subsequent encrypt/decrypt. Reset to None by
# ``_reset_fernet_cache()`` (tests, key rotation).
_fernet_instance: Fernet | None = None


class EncryptionError(RuntimeError):
    """Raised on configuration errors (e.g. missing/invalid encryption key)."""


def _reset_fernet_cache() -> None:
    """Clear the cached Fernet instance (used by tests / key rotation)."""
    global _fernet_instance
    _fernet_instance = None


def _get_fernet() -> Fernet:
    """Build and cache a Fernet cipher from ``settings.MESSAGING_ENCRYPTION_KEY``.

    The key must be a valid url-safe base64-encoded 32-byte Fernet key.
    Generate one with::

        from cryptography.fernet import Fernet
        Fernet.generate_key()

    Raises ``EncryptionError`` if the key is missing or invalid. Callers
    on the **write** path let this propagate (a broken key must block
    the save, never silently store plaintext). Callers on the **read**
    path catch it and degrade gracefully — see :func:`decrypt_value`.
    """
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

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
        _fernet_instance = Fernet(key)
    except (ValueError, TypeError) as exc:
        raise EncryptionError(
            "MESSAGING_ENCRYPTION_KEY is not a valid Fernet key (must be 44 "
            "url-safe base64-encoded characters). Generate one with "
            '`python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"`.'
        ) from exc
    return _fernet_instance


def _is_encrypted_ciphertext(text: str) -> bool:
    """True if ``text`` is valid Fernet ciphertext (decrypts cleanly).

    Fernet tokens always start with ``gAAAAA`` (base64 of the 0x80 version
    byte + timestamp), so that prefix is a cheap pre-filter before the
    real decrypt attempt. Used by ``EncryptedJSONField.get_prep_value``
    to distinguish "already encrypted at rest" from "plaintext string".
    """
    if not text or not text.startswith("gAAAAA"):
        return False
    try:
        _get_fernet().decrypt(text.encode("utf-8"))
        return True
    except Exception:
        return False


def _parse_plaintext(text: str) -> Any:
    """Best-effort parse of a plaintext credential string.

    Handles valid JSON, Python dict-literal strings (legacy single-quoted
    data), and falls back to the raw string so even unparseable values
    get encrypted rather than persisted as plaintext.
    """
    for parser in (json.loads, ast.literal_eval):
        try:
            return parser(text)
        except (ValueError, SyntaxError, TypeError):
            continue
    return text


def encrypt_value(value: Any) -> str:
    """Serialize ``value`` to JSON and return Fernet-encrypted base64 text.

    Raises ``EncryptionError`` if the encryption key is missing or
    invalid — this is intentional so a misconfigured key never results
    in plaintext being persisted.
    """
    if value is None:
        return ""
    raw = json.dumps(value, cls=DjangoJSONEncoder).encode("utf-8")
    return _get_fernet().encrypt(raw).decode("utf-8")


def decrypt_value(text: str) -> Any:
    """Decrypt Fernet text back to a Python object.

    Returns the original raw value if decryption fails for any reason
    (wrong key, legacy plaintext, or a misconfigured key). This keeps
    the application running while the configuration is fixed — a Django
    system check flags the problem at startup.
    """
    if not text:
        return None
    try:
        cipher = _get_fernet()
    except EncryptionError:
        # Key is misconfigured — can't decrypt anything. Return the raw
        # stored text so the app doesn't crash on every credential read.
        logger.error(
            "Cannot decrypt credentials: MESSAGING_ENCRYPTION_KEY is "
            "missing or invalid. Returning raw value. Fix the key in "
            "your .env / environment to restore encryption."
        )
        return text
    try:
        raw = cipher.decrypt(text.encode("utf-8"))
    except InvalidToken:
        # Could be legacy plaintext or a key-rotation artifact. Surface
        # it as-is rather than crashing the read path.
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
            # A string reaching here is either already-encrypted ciphertext
            # (keep as-is, never double-encrypt) or plaintext (parse +
            # encrypt so plaintext never persists at rest).
            if _is_encrypted_ciphertext(value):
                return value
            return encrypt_value(_parse_plaintext(value))
        return encrypt_value(value)

    def value_to_string(self, obj):
        """Serialize the field value for serializers (dumpdata, etc.)."""
        return self.value_from_object(obj)
