"""
WhatsApp Business Cloud API webhook parsing & verification.

Cloud API webhooks:

1. **GET** verification — echoes back ``hub.challenge`` after confirming
   ``hub.verify_token`` (same convention as Facebook).
2. **POST** delivery — wrapped in ``entry[].changes[].value``. We
   normalize ``messages`` (inbound) and ``statuses`` (sent/delivered/
   read/failed receipts).

Verification uses HMAC-SHA256 of the raw body with the App Secret via
the ``X-Hub-Signature-256`` header.

See: https://developers.facebook.com/docs/whatsapp/cloud-api/webhooks/payload-examples
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone

from ..dto import DeliveryUpdate, NormalizedAttachment, NormalizedIncomingEvent
from ..exceptions import WebhookParseError, WebhookVerificationError
from ...constants import AttachmentType, DeliveryStatus, MessageType

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def verify(*, query_params: dict[str, str], body: bytes, headers: dict[str, str], app_secret: str, verify_token: str) -> tuple[bool, str]:
    """Validate a WhatsApp Cloud API webhook request."""
    mode = (query_params.get("hub.mode") or "").lower()

    # Subscription handshake
    if mode == "subscribe":
        token = query_params.get("hub.verify_token", "")
        if not hmac.compare_digest(token, verify_token):
            raise WebhookVerificationError("WhatsApp hub.verify_token mismatch.")
        return True, query_params.get("hub.challenge", "")

    # Event delivery — verify HMAC-SHA256 signature
    signature_header = headers.get("X-Hub-Signature-256") or headers.get("X-Hub-Signature") or ""
    algo = "sha256"
    provided = signature_header
    if "=" in signature_header:
        algo, _, provided = signature_header.partition("=")
    expected = hmac.new(app_secret.encode("utf-8"), body, getattr(hashlib, algo, hashlib.sha256)).hexdigest()
    if not provided or not hmac.compare_digest(provided, expected):
        raise WebhookVerificationError("WhatsApp webhook signature mismatch.")
    return True, ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse(*, body: bytes) -> list[NormalizedIncomingEvent | DeliveryUpdate]:
    """Parse a WhatsApp Cloud API webhook body into normalized events."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WebhookParseError(f"Invalid WhatsApp webhook JSON: {exc}") from exc

    if payload.get("object") != "whatsapp_business_account":
        logger.debug("Ignoring non-whatsapp webhook object=%r", payload.get("object"))
        return []

    events: list[NormalizedIncomingEvent | DeliveryUpdate] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {}) or {}
            try:
                # Inbound messages
                for msg in value.get("messages", []) or []:
                    events.append(_parse_message(msg, value))
                # Status receipts
                for status in value.get("statuses", []) or []:
                    events.append(_parse_status(status))
            except Exception:  # pragma: no cover - defensive per-item
                logger.warning("Failed to parse WA change: %s", value, exc_info=True)
    return events


def _parse_message(msg: dict, value: dict) -> NormalizedIncomingEvent:
    """Parse a WA inbound message object."""
    msg_id = msg.get("id", "")
    sender_phone = msg.get("from", "")
    timestamp = _from_epoch(msg.get("timestamp"))
    msg_type = (msg.get("type") or "text").lower()

    text = ""
    attachments: list[NormalizedAttachment] = []
    location = None
    message_type = MessageType.TEXT.value

    if msg_type == "text":
        text = (msg.get("text") or {}).get("body", "")
    elif msg_type in ("image", "audio", "video", "document", "sticker"):
        block = msg.get(msg_type) or {}
        message_type = {
            "image": MessageType.IMAGE.value,
            "audio": MessageType.AUDIO.value,
            "video": MessageType.VIDEO.value,
            "document": MessageType.DOCUMENT.value,
            "sticker": MessageType.STICKER.value,
        }.get(msg_type, MessageType.OTHER.value)
        attachments.append(
            NormalizedAttachment(
                attachment_type={
                    "image": AttachmentType.IMAGE.value,
                    "audio": AttachmentType.AUDIO.value,
                    "video": AttachmentType.VIDEO.value,
                    "document": AttachmentType.DOCUMENT.value,
                    "sticker": AttachmentType.IMAGE.value,
                }.get(msg_type, AttachmentType.FILE.value),
                external_id=block.get("id", ""),
                mime_type=block.get("mime_type", ""),
                file_name=block.get("filename", ""),
                external_url="",  # media URL is fetched via a separate media API call
                extra=block,
            )
        )
        # Caption rides on the attachment block; surface as message text too.
        text = block.get("caption", "") or ""
    elif msg_type == "location":
        loc = msg.get("location") or {}
        location = {
            "latitude": loc.get("latitude"),
            "longitude": loc.get("longitude"),
            "name": loc.get("name", ""),
            "address": loc.get("address", ""),
        }
        message_type = MessageType.LOCATION.value
    elif msg_type == "button":
        # Button replies carry a text payload.
        text = (msg.get("button") or {}).get("text", "")
        message_type = MessageType.BUTTONS.value
    else:
        message_type = MessageType.OTHER.value

    # Sender display name (WA sometimes includes contacts[name]) and context (reply)
    contacts = value.get("contacts") or []
    display_name = ""
    avatar = ""
    if contacts and sender_phone:
        wa_id = (contacts[0] or {}).get("wa_id", "")
        if wa_id == sender_phone or len(contacts) == 1:
            display_name = (contacts[0] or {}).get("name", "")
    reply_to = (msg.get("context") or {}).get("id", "")

    return NormalizedIncomingEvent(
        external_message_id=msg_id,
        external_timestamp=timestamp,
        sender_external_id=sender_phone,
        sender_display_name=display_name,
        sender_avatar_url=avatar,
        sender_profile={"name": display_name} if display_name else {},
        message_type=message_type,
        text=text,
        attachments=attachments,
        location=location,
        reply_to_external_id=reply_to,
        raw=msg,
    )


def _parse_status(status: dict) -> DeliveryUpdate:
    """Parse a WA status receipt into a DeliveryUpdate."""
    raw_status = (status.get("status") or "").lower()
    status_map = {
        "sent": DeliveryStatus.SENT.value,
        "delivered": DeliveryStatus.DELIVERED.value,
        "read": DeliveryStatus.READ.value,
        "failed": DeliveryStatus.FAILED.value,
        "undelivered": DeliveryStatus.UNDELIVERED.value,
    }
    return DeliveryUpdate(
        external_message_id=status.get("id", ""),
        status=status_map.get(raw_status, DeliveryStatus.SENT.value),
        timestamp=_from_epoch(status.get("timestamp")),
        raw=status,
    )


def _from_epoch(epoch) -> datetime | None:
    """Convert a WA second-precision epoch to an aware datetime."""
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
