"""
Facebook Messenger channel adapter.

Implements ``BaseChannelAdapter`` for the Facebook Messenger platform
(Graph API). This is where Facebook specifics live; the service layer
calls these methods through the registry and never sees FB payloads.

Credentials shape (stored encrypted on ConnectedAccount.credentials):
    {
        "app_id": "...",
        "app_secret": "...",          # used for webhook HMAC verification
        "page_access_token": "...",   # long-lived page token used to send
        "page_id": "...",             # == ConnectedAccount.external_id
    }
"""

from __future__ import annotations

import ast
import json
import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from django.utils import timezone

logger = logging.getLogger(__name__)

from ..base import BaseChannelAdapter
from ..dto import (
    DeliveryUpdate,
    NormalizedIncomingEvent,
    OutboundMessage,
    SendResult,
    VerifyResult,
)
from ..exceptions import AuthenticationError, ConfigurationError, SendMessageError
from ...fields import decrypt_value
from ..registry import register
from . import client, webhook
from ...constants import DeliveryStatus, MessageType

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from ...models import ConnectedAccount


@register("facebook_messenger")
class FacebookAdapter(BaseChannelAdapter):
    """Adapter for Facebook Messenger (Pages via the Graph API)."""

    channel_type = "facebook_messenger"

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------
    def verify_webhook(self, *, method, headers, query_params, body, account) -> tuple[bool, Any]:
        app_secret = self._cred(account, "app_secret")
        if not app_secret:
            logger.error(
                "Facebook webhook verification failed for account %s (%s): app_secret is empty or missing. "
                "Credentials keys available: %s",
                account.id,
                account.name,
                list((account.credentials or {}).keys())
                if isinstance(account.credentials, dict)
                else "not_a_dict",
            )
        # The verify token lives on the account (or in credentials as a
        # fallback); it is distinct from the app secret used for HMAC.
        verify_token = account.webhook_verify_token or self._cred(account, "verify_token")
        ok, challenge = webhook.verify(
            query_params=query_params,
            body=body,
            headers=headers,
            app_secret=app_secret,
            verify_token=verify_token,
        )
        # GET returns the challenge; POST returns "".
        return ok, challenge

    def parse_webhook(
        self, *, headers, body, account
    ) -> list[NormalizedIncomingEvent | DeliveryUpdate]:
        return webhook.parse(body=body)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    def send_message(self, *, account, recipient_external_id, message) -> SendResult:
        if not message.has_content:
            return SendResult(
                success=False, status=DeliveryStatus.FAILED.value, error_message="Empty message"
            )

        payload = self._build_send_payload(recipient_external_id, message)
        logger.debug("Sending Facebook message: payload=%s", payload)
        print("Sending Facebook message: payload=%s", payload)
        try:
            data = client.send(
                account=account, recipient_psid=recipient_external_id, payload=payload
            )
            logger.info("Facebook send successful: data=%s", data)
        except SendMessageError as exc:
            logger.error("Facebook send failed: %s (code=%s)", exc, exc.code)
            print("Facebook send failed: %s (code=%s)", exc, exc.code)
            return SendResult(
                success=False,
                status=DeliveryStatus.FAILED.value,
                error_code=exc.code,
                error_message=str(exc),
            )

        # Send API returns {"recipient_id": "...", "message_id": "..."}
        external_id = (data or {}).get("message_id") or (data or {}).get("id")
        logger.info("Creating SendResult: success=True, external_id=%s, data=%s", external_id, data)
        print("Creating SendResult: success=True, external_id=%s, data=%s", external_id, data)
        return SendResult(
            success=True, external_id=external_id, status=DeliveryStatus.SENT.value, raw=data
        )

    def _build_send_payload(self, psid: str, message: OutboundMessage) -> dict[str, Any]:
        """Translate OutboundMessage into a Graph Send API payload."""
        recipient = {"id": psid}
        if message.reply_to_external_id:
            recipient["recipient_id"] = psid

        msg: dict[str, Any] = {}
        if message.text:
            msg["text"] = message.text

        for att in message.attachments:
            attachment = self._build_attachment(att.attachment_type, att.url or "", att.file)
            if attachment:
                msg.setdefault("attachment", attachment)

        return {
            "recipient": {"id": psid},
            "message": msg,
            "messaging_type": message.extra.get("messaging_type", "RESPONSE"),
        }

    def _build_attachment(self, attachment_type: str, url: str, file_obj) -> dict | None:
        """Build a single FB attachment payload. URL-based only for now."""
        if not url:
            return None
        fb_type = {
            MessageType.IMAGE.value: "image",
            MessageType.AUDIO.value: "audio",
            MessageType.VIDEO.value: "video",
            MessageType.FILE.value: "file",
        }.get(attachment_type, "file")
        return {"type": fb_type, "payload": {"url": url}}

    # ------------------------------------------------------------------
    # Identity / profile
    # ------------------------------------------------------------------
    def fetch_identity_profile(self, *, account, external_id) -> dict[str, Any]:
        profile = client.fetch_profile(account=account, psid=external_id)
        first = profile.get("first_name", "")
        last = profile.get("last_name", "")
        full = f"{first} {last}".strip()
        return {
            "display_name": full or external_id,
            "avatar_url": profile.get("profile_pic", ""),
            "first_name": first,
            "last_name": last,
            "extra": profile,
        }

    # ------------------------------------------------------------------
    # Account connection
    # ------------------------------------------------------------------
    def authenticate_account(self, *, account, credentials) -> dict[str, Any]:
        """Normalize freshly-supplied Facebook credentials.

        Follows Meta's long-lived token best-practice flow:

        1. If a **short-lived user token** is supplied, exchange it for a
           long-lived user token (~60 days).
        2. Use the long-lived user token to fetch long-lived **Page**
           access tokens via ``GET /me/accounts``. Page tokens derived
           from a long-lived user token do not expire while the user
           token remains valid.
        3. Store both tokens + expiry metadata so the periodic refresh
           task can re-fetch page tokens before the user token lapses.

        If a ready ``page_access_token`` is supplied directly (no
        short-lived token), it is stored as-is — but without a user
        token it cannot be auto-refreshed; it will be marked ``expired``
        when it dies.
        """
        app_id = credentials.get("app_id") or self._cred(account, "app_id")
        app_secret = credentials.get("app_secret") or self._cred(account, "app_secret")
        page_token = credentials.get("page_access_token")
        page_id = credentials.get("page_id") or account.external_id

        if not app_id or not app_secret:
            raise ConfigurationError("Facebook connection requires app_id and app_secret.")

        now = timezone.now()
        normalized: dict[str, Any] = {
            "app_id": app_id,
            "app_secret": app_secret,
            "page_id": page_id,
        }

        # --- Path A: short-lived user token → long-lived → page token ---
        short = credentials.get("short_lived_token")
        user_token = credentials.get("long_lived_user_token")

        if short and not page_token:
            # Step 1: exchange short-lived user token for a long-lived one.
            exchanged = client.exchange_long_lived_token(
                app_id=app_id, app_secret=app_secret, short_lived_token=short
            )
            user_token = exchanged.get("access_token", "")
            expires_in = exchanged.get("expires_in")
            if expires_in:
                normalized["user_token_expires_at"] = (
                    now + timedelta(seconds=int(expires_in))
                ).isoformat()

        # If we have (or just obtained) a long-lived user token, use it
        # to fetch the proper long-lived page access token.
        if user_token:
            normalized["user_access_token"] = user_token
            normalized["user_token_obtained_at"] = now.isoformat()
            pages = client.fetch_page_tokens(user_access_token=user_token)
            page = next(
                (p for p in pages if not page_id or p.get("id") == str(page_id)),
                pages[0] if pages else None,
            )
            if page:
                page_token = page.get("access_token", page_token or "")
                if not page_id:
                    page_id = page.get("id", page_id)
                    normalized["page_id"] = page_id
                normalized["page_token_obtained_at"] = now.isoformat()
            # If no page matched, fall through with whatever page_token we had.

        if not page_token:
            raise AuthenticationError(
                "Facebook connection requires a page_access_token "
                "(or a short_lived_token to derive one)."
            )

        normalized["page_access_token"] = page_token
        return normalized

    def verify_credentials(self, *, account) -> VerifyResult:
        """Check the page access token against the Graph API (``GET /me``).

        Confirms the token is valid and the page is reachable, and returns
        the platform-confirmed page name so the UI can show it.
        """
        try:
            data = client.verify_token(account=account)
        except AuthenticationError as exc:
            return VerifyResult(valid=False, error_code="auth_failed", error_message=str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            return VerifyResult(valid=False, error_code="error", error_message=str(exc))
        return VerifyResult(
            valid=True,
            account_name=data.get("name", ""),
            external_id=data.get("id", ""),
            raw=data,
        )

    # ------------------------------------------------------------------
    # Token lifecycle — refresh
    # ------------------------------------------------------------------
    def refresh_credentials(self, *, account) -> bool:
        """Refresh the stored page access token.

        If we hold a long-lived **user** token, re-fetch a fresh page
        token via ``GET /me/accounts`` and persist it. Returns ``True``
        when the credentials were updated, ``False`` when no refresh
        was possible (no user token to refresh with).

        Raises ``AuthenticationError`` when the user token is no longer
        valid — the caller (the periodic Celery task) treats that as
        "mark the account expired".
        """
        user_token = self._cred(account, "user_access_token")
        if not user_token:
            return False  # nothing to refresh with

        page_id = self._cred(account, "page_id") or (account.external_id or "")
        pages = client.fetch_page_tokens(user_access_token=user_token)
        page = next((p for p in pages if p.get("id") == str(page_id)), None)
        if not page and pages:
            page = pages[0]
        if not page:
            raise AuthenticationError("Facebook user token is valid but manages no pages.")

        new_token = page.get("access_token", "")
        if not new_token:
            raise AuthenticationError("Facebook /me/accounts returned no access_token.")

        now = timezone.now()
        creds = self._creds_dict(account)
        creds["page_access_token"] = new_token
        creds["user_access_token"] = user_token
        creds["page_token_obtained_at"] = now.isoformat()
        account.credentials = creds
        account.save(update_fields=["credentials", "updated_at"])
        logger.info("Refreshed page access token for account %s", account.id)
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _creds_dict(self, account: "ConnectedAccount") -> dict[str, Any]:
        """Return the full decrypted credentials dict (mutable copy).

        Handles the same legacy formats as ``_cred`` (encrypted
        ciphertext, JSON string, Python dict-literal string) and always
        returns a plain dict so callers can mutate and re-assign it.
        """
        creds = account.credentials or {}
        if isinstance(creds, str):
            try:
                decrypted = decrypt_value(creds)
                if isinstance(decrypted, dict):
                    return dict(decrypted)
                if isinstance(decrypted, str):
                    try:
                        parsed = json.loads(decrypted)
                        return parsed if isinstance(parsed, dict) else {}
                    except (json.JSONDecodeError, ValueError):
                        try:
                            parsed = ast.literal_eval(decrypted)
                            return dict(parsed) if isinstance(parsed, dict) else {}
                        except (ValueError, SyntaxError):
                            return {}
                elif isinstance(decrypted, dict):
                    return dict(decrypted)
                return {}
            except Exception:
                return {}
        return dict(creds) if isinstance(creds, dict) else {}

    def _cred(self, account: "ConnectedAccount", key: str, default: str = "") -> str:
        """Safely extract a credential value from the account's credentials.

        The credentials field is an EncryptedJSONField that stores encrypted JSON.
        If the field returns a string (encrypted ciphertext or plaintext JSON),
        we decrypt/parse it to get the dict.
        """
        creds = account.credentials or {}

        # If credentials is a string, it might be:
        # 1. Encrypted ciphertext (starts with 'gAAAAA' for Fernet)
        # 2. Plaintext JSON string (double-quoted)
        # 3. Python dict string (single-quoted, from str(dict))
        if isinstance(creds, str):
            # Try to decrypt (returns original if not encrypted)
            try:
                decrypted = decrypt_value(creds)
                # decrypt_value may return a string (plaintext or failed decryption)
                # or a dict (if encrypted content was successfully parsed)
                if isinstance(decrypted, dict):
                    creds = decrypted
                elif isinstance(decrypted, str):
                    # Try to parse as JSON (double-quoted)
                    try:
                        creds = json.loads(decrypted)
                    except (json.JSONDecodeError, ValueError):
                        # Try to parse as Python dict literal (single-quoted)
                        try:
                            creds = ast.literal_eval(decrypted)
                            if not isinstance(creds, dict):
                                logger.warning(
                                    "Parsed credentials is not a dict for account %s", account.id
                                )
                                return default
                        except (ValueError, SyntaxError):
                            logger.warning(
                                "Could not parse credentials as JSON or Python dict for account %s",
                                account.id,
                            )
                            return default
                else:
                    creds = decrypted
            except Exception as e:
                logger.error(
                    "Failed to decrypt/parse credentials for account %s: %s", account.id, e
                )
                return default

        # At this point, creds should be a dict (or None)
        if isinstance(creds, dict):
            value = creds.get(key, default)
            logger.debug(
                "Retrieved credential '%s' for account %s: %s",
                key,
                account.id,
                "✓" if value else "empty",
            )
            return value or default

        logger.warning(
            "Credentials for account %s is not a dict: %s", account.id, type(creds).__name__
        )
        return default
