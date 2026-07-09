"""
WhatsApp Business (Cloud API) channel adapter.

Implements ``BaseChannelAdapter`` for the WhatsApp Cloud API. Cloud API
specifics live here; the service layer is unaware of them.

Credentials shape (stored encrypted on ConnectedAccount.credentials):
    {
        "access_token": "...",       # Meta system-user token
        "phone_number_id": "...",    # == ConnectedAccount.external_id
        "waba_id": "...",            # WhatsApp Business Account id
        "app_secret": "...",         # webhook HMAC verification
        "verify_token": "...",       # webhook subscription handshake
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


@register("whatsapp")
class WhatsAppAdapter(BaseChannelAdapter):
    """Adapter for WhatsApp Business via the Cloud API."""

    channel_type = "whatsapp"

    # ------------------------------------------------------------------
    # Webhooks
    # ------------------------------------------------------------------
    def verify_webhook(self, *, method, headers, query_params, body, account) -> tuple[bool, Any]:
        app_secret = self._cred(account, "app_secret")
        verify_token = self._cred(account, "verify_token") or account.webhook_verify_token
        ok, challenge = webhook.verify(
            query_params=query_params,
            body=body,
            headers=headers,
            app_secret=app_secret,
            verify_token=verify_token,
        )
        return ok, challenge

    def parse_webhook(self, *, headers, body, account) -> list[NormalizedIncomingEvent | DeliveryUpdate]:
        return webhook.parse(body=body)

    # ------------------------------------------------------------------
    # Sending
    # ------------------------------------------------------------------
    def send_message(self, *, account, recipient_external_id, message) -> SendResult:
        if not message.has_content:
            return SendResult(success=False, status=DeliveryStatus.FAILED.value, error_message="Empty message")

        # Template send vs free-form send have different payload shapes.
        if message.template_name:
            payload = self._build_template_payload(recipient_external_id, message)
        else:
            payload = self._build_text_payload(recipient_external_id, message)

        try:
            data = client.send(account=account, payload=payload)
        except SendMessageError as exc:
            return SendResult(
                success=False,
                status=DeliveryStatus.FAILED.value,
                error_code=exc.code,
                error_message=str(exc),
            )

        # Cloud API: {"messaging_product":"whatsapp","messages":[{"id":"..."}]}
        messages = (data or {}).get("messages") or []
        external_id = messages[0].get("id") if messages else None
        return SendResult(success=True, external_id=external_id, status=DeliveryStatus.SENT.value, raw=data)

    def _build_text_payload(self, phone: str, message: OutboundMessage) -> dict[str, Any]:
        """Build a free-form text/media send payload."""
        base = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": phone}

        # Attachment takes precedence over text in WhatsApp (one type per message).
        if message.attachments:
            att = message.attachments[0]
            type_map = {
                MessageType.IMAGE.value: "image",
                MessageType.AUDIO.value: "audio",
                MessageType.VIDEO.value: "video",
                MessageType.FILE.value: "document",
                MessageType.DOCUMENT.value: "document",
            }
            wa_type = type_map.get(att.attachment_type, "document")
            block: dict[str, Any] = {}
            if att.url:
                block["link"] = att.url
            if message.text:  # caption
                block["caption"] = message.text
            return {**base, "type": wa_type, wa_type: block}

        return {**base, "type": "text", "text": {"body": message.text, "preview_url": True}}

    def _build_template_payload(self, phone: str, message: OutboundMessage) -> dict[str, Any]:
        """Build a template (HSM) send payload."""
        template = {
            "name": message.template_name,
            "language": {"code": message.template_language or "en_US"},
        }
        if message.template_variables:
            components = []
            body_params = [{"type": "text", "text": str(v)} for v in message.template_variables.values()]
            if body_params:
                components.append({"type": "body", "parameters": body_params})
            template["components"] = components
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": phone,
            "type": "template",
            "template": template,
        }

    # ------------------------------------------------------------------
    # Identity / profile
    # ------------------------------------------------------------------
    def fetch_identity_profile(self, *, account, external_id) -> dict[str, Any]:
        # Cloud API contact lookup is best-effort and may be unavailable;
        # the inbound webhook usually carries the name already.
        data = client.fetch_contacts(account=account, phones=[external_id])
        contacts = (data or {}).get("contacts") or []
        if contacts:
            name = contacts[0].get("name", "")
            return {"display_name": name or external_id, "avatar_url": "", "extra": contacts[0]}
        return {"display_name": external_id, "avatar_url": "", "extra": {}}

    # ------------------------------------------------------------------
    # Account connection
    # ------------------------------------------------------------------
    def authenticate_account(self, *, account, credentials) -> dict[str, Any]:
        """Validate and normalize WhatsApp Cloud API credentials."""
        access_token = credentials.get("access_token")
        phone_number_id = credentials.get("phone_number_id") or account.external_id
        waba_id = credentials.get("waba_id", "")
        app_secret = credentials.get("app_secret", "")
        verify_token = credentials.get("verify_token") or account.webhook_verify_token

        if not access_token:
            raise AuthenticationError("WhatsApp connection requires an access_token.")
        if not phone_number_id:
            raise ConfigurationError("WhatsApp connection requires a phone_number_id.")

        return {
            "access_token": access_token,
            "phone_number_id": phone_number_id,
            "waba_id": waba_id,
            "app_secret": app_secret,
            "verify_token": verify_token,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _cred(self, account: "ConnectedAccount", key: str, default: str = "") -> str:
        return (account.credentials or {}).get(key, default) or default
