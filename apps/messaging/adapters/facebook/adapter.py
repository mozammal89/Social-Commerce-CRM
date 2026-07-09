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

from typing import TYPE_CHECKING, Any

from ..base import BaseChannelAdapter
from ..dto import (
    DeliveryUpdate,
    NormalizedIncomingEvent,
    OutboundMessage,
    SendResult,
)
from ..exceptions import AuthenticationError, ConfigurationError, SendMessageError
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

    def parse_webhook(self, *, headers, body, account) -> list[NormalizedIncomingEvent | DeliveryUpdate]:
        return webhook.parse(body=body)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    def send_message(self, *, account, recipient_external_id, message) -> SendResult:
        if not message.has_content:
            return SendResult(success=False, status=DeliveryStatus.FAILED.value, error_message="Empty message")

        payload = self._build_send_payload(recipient_external_id, message)
        try:
            data = client.send(account=account, recipient_psid=recipient_external_id, payload=payload)
        except SendMessageError as exc:
            return SendResult(
                success=False,
                status=DeliveryStatus.FAILED.value,
                error_code=exc.code,
                error_message=str(exc),
            )

        # Send API returns {"recipient_id": "...", "message_id": "..."}
        external_id = (data or {}).get("message_id") or (data or {}).get("id")
        return SendResult(success=True, external_id=external_id, status=DeliveryStatus.SENT.value, raw=data)

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
        if message.quick_replies:
            msg["quick_replies"] = message.quick_replies

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

        Accepts either a ready long-lived ``page_access_token`` (preferred)
        or a short-lived user token to exchange via the app secret. Returns
        the normalized dict to persist (encrypted) on the account.
        """
        app_id = credentials.get("app_id") or self._cred(account, "app_id")
        app_secret = credentials.get("app_secret") or self._cred(account, "app_secret")
        page_token = credentials.get("page_access_token")
        page_id = credentials.get("page_id") or account.external_id

        if not app_id or not app_secret:
            raise ConfigurationError("Facebook connection requires app_id and app_secret.")

        # Exchange a short-lived user token if that's what was supplied.
        short = credentials.get("short_lived_token")
        if short and not page_token:
            exchanged = client.exchange_long_lived_token(
                app_id=app_id, app_secret=app_secret, short_lived_token=short
            )
            # The long-lived USER token is returned; in production the
            # store owner then grants page permissions and we'd fetch the
            # page token via /me/accounts. For this adapter the page token
            # is expected to be supplied directly.
            page_token = exchanged.get("access_token", "")

        if not page_token:
            raise AuthenticationError("Facebook connection requires a page_access_token.")

        return {
            "app_id": app_id,
            "app_secret": app_secret,
            "page_access_token": page_token,
            "page_id": page_id,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _cred(self, account: "ConnectedAccount", key: str, default: str = "") -> str:
        return (account.credentials or {}).get(key, default) or default
