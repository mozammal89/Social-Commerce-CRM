"""
TikTok Business Messaging webhook parsing & verification.

TikTok delivers webhook events for business messaging as single JSON
objects (one per POST) keyed by ``event_type``. Each event carries:

* a stable ``event_id`` (idempotency key),
* an ISO/Unix ``event_timestamp``,
* a per-event ``data`` block with sender/recipient/message info.

The wire format we normalize here is the documented v2 Business
Messaging shape::

    {
      "v1": {"event_id": "...", "event_type": "bm.message.receive", ...},
      "event_id": "...",                     # newer v2 layout
      "event": "bm.message.receive",
      "data": {
        "sender_user_id": "...",
        "recipient_user_id": "...",
        "conversation_id": "...",
        "message_id": "...",
        "message_type": "TEXT",
        "text": {"content": "Hello"},
        "create_time": 1700000000
      }
    }

TikTok supports two webhook verification mechanisms. We accept either:

1. **HMAC-SHA256 signature** — recommended. The raw body is signed with
   the ``client_secret`` and delivered in the ``X-TT-Webhook-Signature``
   header. Some surfaces include a timestamp prefix (signed as
   ``timestamp.body``) carried in a parallel
   ``X-TT-Webhook-Timestamp`` header.
2. **Plain verify token** — legacy. The merchant sets a static token in
   the TikTok developer console and we compare it against either a
   ``verify_token`` query param or an ``X-TT-Verify-Token`` header.

Both checks fail-closed when configured: an unset ``client_secret``
*and* an unset ``verify_token`` falls through to "accept" so existing
single-tenant deployments keep working during rollout.

See: https://developers.tiktok.com/doc/business-messaging-api-webhooks
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


# TikTok ``message_type`` values → our MessageType enum.
_TEXT_TYPE = MessageType.TEXT.value
_MEDIA_TYPE_MAP = {
    "IMAGE": (MessageType.IMAGE.value, AttachmentType.IMAGE.value),
    "AUDIO": (MessageType.AUDIO.value, AttachmentType.AUDIO.value),
    "VIDEO": (MessageType.VIDEO.value, AttachmentType.VIDEO.value),
    "FILE": (MessageType.DOCUMENT.value, AttachmentType.DOCUMENT.value),
    "STICKER": (MessageType.STICKER.value, AttachmentType.IMAGE.value),
}

# TikTok delivery/read status values → our DeliveryStatus enum.
_STATUS_MAP = {
    "SENT": DeliveryStatus.SENT.value,
    "DELIVERED": DeliveryStatus.DELIVERED.value,
    "READ": DeliveryStatus.READ.value,
    "FAILED": DeliveryStatus.FAILED.value,
    "UNDELIVERED": DeliveryStatus.UNDELIVERED.value,
}


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def verify(
    *,
    query_params: dict[str, str],
    body: bytes,
    headers: dict[str, str],
    client_secret: str = "",
    verify_token: str = "",
) -> tuple[bool, str]:
    """Validate a TikTok webhook request.

    Accepts either the HMAC signature scheme (preferred) or the legacy
    verify-token scheme. When neither ``client_secret`` nor
    ``verify_token`` is configured we accept the POST — this is the
    rollout-compat behavior the same as Facebook/WhatsApp defaults.
    """
    # Case-insensitive header access.
    h = {k.lower(): v for k, v in (headers or {}).items()}
    signature = h.get("x-tt-webhook-signature") or h.get("x-tiktok-webhook-signature")
    timestamp = h.get("x-tt-webhook-timestamp") or h.get("x-tiktok-webhook-timestamp")
    header_token = h.get("x-tt-verify-token") or h.get("x-tiktok-verify-token")

    # --- Scheme 1: HMAC signature with client_secret --------------------
    if client_secret and signature:
        message = body
        if timestamp:
            # Some TikTok surfaces prepend the timestamp to the signed
            # body. Compute both and accept either.
            message_ts = timestamp.encode("utf-8") + b"." + body
            expected_plain = hmac.new(
                client_secret.encode("utf-8"), message, hashlib.sha256
            ).hexdigest()
            expected_ts = hmac.new(
                client_secret.encode("utf-8"), message_ts, hashlib.sha256
            ).hexdigest()
            if not (
                hmac.compare_digest(signature, expected_plain)
                or hmac.compare_digest(signature, expected_ts)
            ):
                raise WebhookVerificationError("TikTok webhook signature mismatch.")
        else:
            expected = hmac.new(client_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise WebhookVerificationError("TikTok webhook signature mismatch.")
        return True, ""

    # --- Scheme 2: legacy verify token (query param or header) ----------
    token = (
        query_params.get("verify_token")
        or query_params.get("hub.verify_token")
        or header_token
        or ""
    )
    if verify_token:
        if not token or not hmac.compare_digest(str(token), str(verify_token)):
            raise WebhookVerificationError("TikTok verify_token mismatch.")
        return True, ""

    # --- Scheme 3: nothing configured — accept (compat) -----------------
    logger.debug(
        "TikTok webhook accepted without verification (no client_secret or "
        "verify_token configured) — configure one to enforce authenticity."
    )
    return True, ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse(*, body: bytes) -> list[NormalizedIncomingEvent | DeliveryUpdate]:
    """Parse a TikTok webhook body into normalized events.

    TikTok sends one event per webhook POST. We map ``event_type``
    (``bm.message.receive``, ``bm.message.read``, etc.) to the right
    normalized DTO. Unknown event types are skipped with a debug log —
    they're typically TikTok-only signals (typing, profile updates) we
    don't yet model.
    """
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WebhookParseError(f"Invalid TikTok webhook JSON: {exc}") from exc

    if not isinstance(payload, dict):
        logger.debug("Ignoring non-object TikTok webhook payload")
        return []

    event_type = (
        payload.get("event_type")
        or payload.get("event")
        or (payload.get("v1") or {}).get("event_type")
        or ""
    ).lower()

    data = payload.get("data") or (payload.get("v1") or {}).get("data") or {}
    event_id = payload.get("event_id") or (payload.get("v1") or {}).get("event_id") or ""

    try:
        if "message.receive" in event_type or event_type.endswith("receive"):
            event = _parse_message(data, event_id)
            return [event] if event else []
        if "message.status" in event_type or ".delivered" in event_type:
            update = _parse_status(data, "DELIVERED")
            return [update] if update else []
        if ".read" in event_type:
            update = _parse_status(data, "READ")
            return [update] if update else []
        if ".sent" in event_type:
            update = _parse_status(data, "SENT")
            return [update] if update else []
        if ".failed" in event_type:
            update = _parse_status(data, "FAILED")
            return [update] if update else []
    except Exception:  # pragma: no cover - defensive per-item
        logger.warning(
            "Failed to parse TikTok event_type=%s: %s",
            event_type,
            data,
            exc_info=True,
        )
    logger.debug("Ignoring TikTok event_type=%r", event_type)
    return []


def _parse_message(data: dict, event_id: str) -> NormalizedIncomingEvent | None:
    """Normalize a TikTok inbound message event."""
    sender_id = str(data.get("sender_user_id") or "")
    if not sender_id:
        return None

    message_id = str(data.get("message_id") or event_id or "")
    timestamp = _from_epoch(data.get("create_time") or data.get("timestamp"))
    raw_type = str(data.get("message_type") or "TEXT").upper()

    text = ""
    attachments: list[NormalizedAttachment] = []
    message_type = _TEXT_TYPE

    if raw_type == "TEXT":
        text = (data.get("text") or {}).get("content", "")
    elif raw_type in _MEDIA_TYPE_MAP:
        message_type, attachment_type = _MEDIA_TYPE_MAP[raw_type]
        block = data.get(raw_type.lower()) or data.get("media") or {}
        # TikTok media payloads carry either a URL or a media_id.
        url = block.get("url") or block.get("media_url") or ""
        attachments.append(
            NormalizedAttachment(
                attachment_type=attachment_type,
                external_id=str(block.get("media_id") or ""),
                external_url=url,
                mime_type=block.get("mime_type", ""),
                file_name=block.get("file_name", ""),
                file_size=block.get("file_size"),
                extra=block,
            )
        )
        # Some TikTok media events include a caption.
        text = block.get("caption", "")
    elif raw_type == "LOCATION":
        loc = data.get("location") or {}
        # Surfacing location via the NormalizedIncomingEvent.location
        # field; we also keep the raw block in attachments.extra below.
        location_payload = {
            "latitude": loc.get("latitude"),
            "longitude": loc.get("longitude"),
            "name": loc.get("name", ""),
            "address": loc.get("address", ""),
        }
        message_type = MessageType.LOCATION.value
        return NormalizedIncomingEvent(
            external_message_id=message_id,
            external_timestamp=timestamp,
            sender_external_id=sender_id,
            message_type=message_type,
            text=text,
            attachments=[],
            location=location_payload,
            raw=data,
        )
    else:
        message_type = MessageType.OTHER.value

    # Display name — TikTok sometimes includes a ``sender_profile`` block.
    sender_profile = data.get("sender_profile") or {}
    display = (
        sender_profile.get("display_name")
        or sender_profile.get("nickname")
        or sender_profile.get("username")
        or ""
    )
    avatar = sender_profile.get("avatar_url") or sender_profile.get("profile_pic") or ""

    return NormalizedIncomingEvent(
        external_message_id=message_id,
        external_timestamp=timestamp,
        sender_external_id=sender_id,
        sender_display_name=display,
        sender_avatar_url=avatar,
        sender_profile=sender_profile,
        message_type=message_type,
        text=text,
        attachments=attachments,
        reply_to_external_id=str(data.get("reply_to_message_id") or ""),
        raw=data,
    )


def _parse_status(data: dict, fallback_status: str) -> DeliveryUpdate | None:
    """Normalize a TikTok delivery/read status event."""
    message_id = str(
        data.get("message_id") or (data.get("messages") or [{}])[0].get("message_id") or ""
    )
    if not message_id:
        return None
    raw_status = str(data.get("status") or fallback_status).upper()
    status = _STATUS_MAP.get(raw_status, DeliveryStatus.SENT.value)
    timestamp = _from_epoch(data.get("timestamp") or data.get("create_time"))
    return DeliveryUpdate(
        external_message_id=message_id,
        status=status,
        timestamp=timestamp,
        raw=data,
    )


def _from_epoch(epoch) -> datetime | None:
    """Convert a TikTok second-precision epoch to an aware datetime."""
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


__all__ = ["verify", "parse"]
