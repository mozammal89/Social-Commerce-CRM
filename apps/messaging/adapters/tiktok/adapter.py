"""
TikTok Business Messaging channel adapter.

Implements ``BaseChannelAdapter`` for TikTok's Business Messaging API
on the TikTok Open Platform (``open.tiktokapis.com``).

TikTok Business Messaging uses standard OAuth 2.0: the merchant
authorizes the CRM app to message on behalf of their TikTok Business
Account, and we receive an ``access_token`` (valid ~24h) plus a
``refresh_token`` (valid ~30 days). The periodic refresh task uses the
refresh token to keep the access token alive.

Webhook verification supports both schemes TikTok offers:

* **HMAC-SHA256 signature** in ``X-TT-Webhook-Signature`` (recommended)
  computed with the ``client_secret``.
* **Plain verify token** in a query param or header (legacy).

Credentials shape (stored encrypted on ConnectedAccount.credentials):
    {
        "client_key": "...",
        "client_secret": "...",   # OAuth secret; also webhook HMAC key
        "access_token": "...",    # short-lived (~24h)
        "refresh_token": "...",   # long-lived (~30 days)
        "business_id": "...",     # == ConnectedAccount.external_id
        "open_id": "...",         # the merchant's TikTok user id
        "access_token_expires_at": "...",   # ISO timestamp
        "refresh_token_expires_at": "..."
    }
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any, Optional

from django.utils import timezone

from ..base import BaseChannelAdapter
from ..dto import (
    DeliveryUpdate,
    NormalizedIncomingEvent,
    OutboundMessage,
    SendResult,
    VerifyResult,
)
from ..exceptions import AuthenticationError, ConfigurationError, SendMessageError
from ..registry import register
from . import client, webhook
from ...constants import AttachmentType, DeliveryStatus, MessageType

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    from ...models import ConnectedAccount

logger = logging.getLogger(__name__)

# How early (seconds) before expiry we should refresh.
_REFRESH_LEEWAY_SECONDS = 60 * 10  # 10 min


@register("tiktok")
class TikTokAdapter(BaseChannelAdapter):
    """Adapter for TikTok Business Messaging."""

    channel_type = "tiktok"

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------
    def verify_webhook(self, *, method, headers, query_params, body, account) -> tuple[bool, Any]:
        client_secret = self._cred(account, "client_secret")
        verify_token = account.webhook_verify_token or self._cred(account, "verify_token")
        ok, challenge = webhook.verify(
            query_params=query_params,
            body=body,
            headers=headers,
            client_secret=client_secret,
            verify_token=verify_token,
        )
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
                success=False,
                status=DeliveryStatus.FAILED.value,
                error_message="Empty message",
            )

        payload = self._build_send_payload(recipient_external_id, message)
        try:
            data = client.send_message(account=account, payload=payload)
        except SendMessageError as exc:
            logger.error("TikTok send failed: %s (code=%s)", exc, exc.code)
            return SendResult(
                success=False,
                status=DeliveryStatus.FAILED.value,
                error_code=exc.code,
                error_message=str(exc),
            )

        # TikTok's send response: {"data": {"message_id": "..."}}
        block = (data or {}).get("data") or {}
        external_id = block.get("message_id") or block.get("id")
        return SendResult(
            success=True,
            external_id=external_id,
            status=DeliveryStatus.SENT.value,
            raw=data,
        )

    def _build_send_payload(
        self, recipient_user_id: str, message: OutboundMessage
    ) -> dict[str, Any]:
        """Translate OutboundMessage into a TikTok send payload.

        TikTok's ``/v2/business/msg/sendmessage`` body requires:

            {
              "sender_user_id": "<business's TikTok user id>",
              "recipient_user_id": "<customer's TikTok user id>",
              "message_type": "TEXT"|"IMAGE"|...,
              "text":     {"content": "..."},   # for TEXT
              "image":    {"url": "..."},        # for IMAGE
              ...
            }

        We set ``sender_user_id`` from ``message.extra['sender_external_id']``
        (the connected account's ``external_id`` / open_id), which the
        service layer is expected to populate when handing us the
        outbound message.
        """
        sender = self._sender_id_from(message)

        body: dict[str, Any] = {
            "sender_user_id": sender,
            "recipient_user_id": recipient_user_id,
        }

        if message.attachments:
            att = message.attachments[0]
            tt_type, content_key = self._media_field_for(att.attachment_type)
            body["message_type"] = tt_type
            media_payload: dict[str, Any] = {}
            if att.url:
                media_payload["url"] = att.url
            if message.text:
                media_payload["caption"] = message.text
            body[content_key] = media_payload
            return body

        if message.message_type == MessageType.LOCATION.value and message.extra.get("location"):
            loc = message.extra["location"]
            body["message_type"] = "LOCATION"
            body["location"] = {
                "latitude": loc.get("latitude"),
                "longitude": loc.get("longitude"),
                "name": loc.get("name", ""),
            }
            return body

        # Plain text.
        body["message_type"] = "TEXT"
        body["text"] = {"content": message.text}
        return body

        if message.message_type == MessageType.LOCATION.value and message.extra.get("location"):
            loc = message.extra["location"]
            body["message_type"] = "LOCATION"
            body["location"] = {
                "latitude": loc.get("latitude"),
                "longitude": loc.get("longitude"),
                "name": loc.get("name", ""),
            }
            return body

        # Plain text.
        body["message_type"] = "TEXT"
        body["text"] = {"content": message.text}
        return body

    def _sender_id_from(self, message: OutboundMessage) -> str:
        """Resolve the business's sender id from message.extra.

        The service layer is expected to populate
        ``message.extra['sender_external_id']`` with the connected
        account's ``external_id`` (business_id / open_id). Defaults to
        ``""`` — TikTok will reject the call, which surfaces as a clear
        SendMessageError so the caller can fix the wiring.
        """
        sender = message.extra.get("sender_external_id", "")
        if not sender:
            raise SendMessageError(
                "TikTok send requires a sender_external_id (the business's "
                "TikTok user id) — pass it via OutboundMessage.extra.",
                code="missing_sender",
            )
        return sender

    @staticmethod
    def _media_field_for(attachment_type: str) -> tuple[str, str]:
        """Map our attachment type → (tiktok_type, content_key)."""
        mapping = {
            MessageType.IMAGE.value: ("IMAGE", "image"),
            MessageType.AUDIO.value: ("AUDIO", "audio"),
            MessageType.VIDEO.value: ("VIDEO", "video"),
            MessageType.DOCUMENT.value: ("FILE", "file"),
            MessageType.FILE.value: ("FILE", "file"),
            AttachmentType.IMAGE.value: ("IMAGE", "image"),
            AttachmentType.AUDIO.value: ("AUDIO", "audio"),
            AttachmentType.VIDEO.value: ("VIDEO", "video"),
            AttachmentType.DOCUMENT.value: ("FILE", "file"),
            AttachmentType.FILE.value: ("FILE", "file"),
        }
        return mapping.get(attachment_type, ("FILE", "file"))

    # ------------------------------------------------------------------
    # Identity / profile
    # ------------------------------------------------------------------
    def fetch_identity_profile(self, *, account, external_id) -> dict[str, Any]:
        """Fetch the TikTok profile for a user id.

        TikTok exposes ``display_name``, ``avatar_url`` and
        ``profile_deep_link`` for messaging users. Locale/timezone are
        not part of the messaging profile, so those keys default to
        ``""`` (per the contract).
        """
        profile = client.get_user_info(account=account, user_id=external_id)
        display = (
            profile.get("display_name")
            or profile.get("nickname")
            or profile.get("username")
            or external_id
        )
        return {
            "display_name": display,
            "avatar_url": profile.get("avatar_url") or profile.get("profile_pic") or "",
            "first_name": "",
            "last_name": "",
            "language": "",
            "timezone": "",
            "extra": profile,
        }

    # ------------------------------------------------------------------
    # Account connection
    # ------------------------------------------------------------------
    def authenticate_account(self, *, account, credentials) -> dict[str, Any]:
        """Validate and normalize TikTok OAuth credentials.

        Accepts either a freshly-exchanged token bundle
        (``access_token`` + ``refresh_token`` + ``expires_in``) or a
        raw ``authorization_code`` from the OAuth redirect, which we
        then exchange. ``client_key`` / ``client_secret`` come from the
        app config and may be supplied per-account for multi-tenant
        overrides.
        """
        client_key = credentials.get("client_key") or self._cred(account, "client_key")
        client_secret = credentials.get("client_secret") or self._cred(account, "client_secret")
        if not client_key or not client_secret:
            raise ConfigurationError("TikTok connection requires client_key and client_secret.")

        access_token = credentials.get("access_token")
        refresh_token = credentials.get("refresh_token")
        business_id = credentials.get("business_id") or account.external_id
        open_id = credentials.get("open_id") or self._cred(account, "open_id")

        # If an authorization_code was supplied (OAuth redirect), we
        # can't exchange it here without an HTTP call into TikTok's
        # /v2/oauth/token — that's typically handled by the connect UI
        # (or a future ``client.exchange_code``). We surface a clear
        # error so the wiring is obvious.
        code = credentials.get("authorization_code") or credentials.get("code")
        if code and not access_token:
            raise ConfigurationError(
                "TikTok authorization_code exchange is not yet supported in the "
                "adapter — exchange it for tokens in the connect UI and pass "
                "access_token + refresh_token."
            )

        if not access_token:
            raise ConfigurationError(
                "TikTok connection requires an access_token (and refresh_token)."
            )

        now = timezone.now()
        normalized: dict[str, Any] = {
            "client_key": client_key,
            "client_secret": client_secret,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "business_id": business_id,
            "open_id": open_id,
        }

        if credentials.get("expires_in"):
            normalized["access_token_expires_at"] = (
                now + timedelta(seconds=int(credentials["expires_in"]))
            ).isoformat()
        if credentials.get("refresh_expires_in"):
            normalized["refresh_token_expires_at"] = (
                now + timedelta(seconds=int(credentials["refresh_expires_in"]))
            ).isoformat()

        return normalized

    def verify_credentials(self, *, account) -> VerifyResult:
        """Check the access token + business id via ``GET /v2/business/get/``."""
        try:
            data = client.get_business_info(account=account)
        except AuthenticationError as exc:
            return VerifyResult(valid=False, error_code="auth_failed", error_message=str(exc))
        except Exception as exc:  # pragma: no cover - defensive
            return VerifyResult(valid=False, error_code="error", error_message=str(exc))
        block = (data or {}).get("data") or {}
        name = block.get("name") or block.get("business_name") or ""
        return VerifyResult(
            valid=True,
            account_name=name,
            external_id=str(block.get("business_id") or ""),
            raw=data,
        )

    # ------------------------------------------------------------------
    # Token lifecycle — refresh
    # ------------------------------------------------------------------
    def refresh_credentials(self, *, account) -> bool:
        """Refresh the TikTok access token using the stored refresh token.

        Returns ``True`` when the credentials were refreshed and
        persisted, ``False`` when no refresh was possible (no refresh
        token). Raises ``AuthenticationError`` when the refresh token is
        no longer valid — the periodic task marks the account expired.
        """
        client_key = self._cred(account, "client_key")
        client_secret = self._cred(account, "client_secret")
        refresh_token = self._cred(account, "refresh_token")
        if not (client_key and client_secret and refresh_token):
            return False

        try:
            data = client.refresh_access_token(
                client_key=client_key,
                client_secret=client_secret,
                refresh_token=refresh_token,
            )
        except AuthenticationError:
            raise

        block = (data or {}).get("data") or {}
        new_access = block.get("access_token", "")
        new_refresh = block.get("refresh_token", "")
        if not new_access:
            raise AuthenticationError("TikTok token refresh returned no access_token.")

        now = timezone.now()
        creds = client._creds(account)
        creds["access_token"] = new_access
        if new_refresh:
            creds["refresh_token"] = new_refresh
        expires_in = block.get("expires_in")
        if expires_in:
            creds["access_token_expires_at"] = (
                now + timedelta(seconds=int(expires_in))
            ).isoformat()
        refresh_expires_in = block.get("refresh_expires_in")
        if refresh_expires_in:
            creds["refresh_token_expires_at"] = (
                now + timedelta(seconds=int(refresh_expires_in))
            ).isoformat()
        account.credentials = creds
        account.save(update_fields=["credentials", "updated_at"])
        logger.info("Refreshed TikTok access token for account %s", account.id)
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _cred(self, account: Optional["ConnectedAccount"], key: str, default: str = "") -> str:
        """Safely extract a credential value from the account."""
        if account is None:
            return default
        return client._creds(account).get(key, default) or default
