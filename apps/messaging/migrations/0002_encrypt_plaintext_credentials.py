"""Data migration: backfill plaintext credentials to encrypted at rest.

Background
----------
``EncryptedJSONField`` encrypts ``ConnectedAccount.credentials`` with
Fernet on write and decrypts on read. However, a handful of legacy rows
were written before the field existed (or via a path that bypassed the
ORM), so their credentials persist as **plaintext** in the database —
JSON or Python dict-literal strings like ``{'app_id': '...', 'app_secret': '...'}``.

This migration scans every row, detects plaintext (i.e. values that fail
Fernet decryption), parses them, re-serializes to canonical JSON, and
writes them back encrypted. It is **idempotent**: running it twice is a
no-op because already-encrypted values decrypt successfully and are skipped.

The reverse is intentionally a no-op — one-way encryption only.

The migration uses raw SQL (not the ORM) because the ORM field would
transparently decrypt on read and re-encrypt on write, which would mask
the plaintext rows we need to inspect and could double-encrypt partial
data mid-transaction. Reading the raw column text is the only reliable
way to distinguish plaintext from ciphertext here.
"""

import ast
import json

from django.db import migrations


def encrypt_plaintext_credentials(apps, schema_editor):
    from cryptography.fernet import Fernet, InvalidToken
    from django.conf import settings
    from django.db import connection

    key = getattr(settings, "MESSAGING_ENCRYPTION_KEY", None)
    if not key:
        # Without a key we cannot encrypt; leave data untouched so the
        # migration is still safe to run in a stripped-down environment.
        return
    fernet = Fernet(key.encode("utf-8") if isinstance(key, str) else key)

    table = "messaging_connected_account"
    with connection.cursor() as cur:
        cur.execute(f"SELECT id, credentials FROM {table}")
        rows = cur.fetchall()

    fixed = 0
    for rid, raw in rows:
        if not raw:
            continue

        # Already encrypted at rest? Skip (idempotent).
        try:
            fernet.decrypt(raw.encode("utf-8"))
            continue
        except (InvalidToken, Exception):
            pass

        # Plaintext — parse it (JSON or Python dict-literal), encrypt, write back.
        parsed = None
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed = parser(raw)
                break
            except (ValueError, SyntaxError, TypeError):
                continue
        if parsed is None:
            parsed = raw  # unparseable scalar — still encrypt it

        payload = json.dumps(parsed).encode("utf-8")
        encrypted = fernet.encrypt(payload).decode("utf-8")
        with connection.cursor() as cur:
            cur.execute(
                f"UPDATE {table} SET credentials = %s WHERE id = %s",
                [encrypted, str(rid)],
            )
        fixed += 1

    if fixed:
        import logging

        logging.getLogger(__name__).info(
            "encrypt_plaintext_credentials: encrypted %d plaintext credential row(s).",
            fixed,
        )


def reverse(apps, schema_editor):
    """No-op: we never decrypt credentials on rollback."""
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("messaging", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(encrypt_plaintext_credentials, reverse),
    ]
