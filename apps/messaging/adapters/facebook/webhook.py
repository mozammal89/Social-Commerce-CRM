"""
Facebook Messenger webhook parsing & verification.

Facebook sends two kinds of webhook to the same URL:

1. **GET** subscription verification — echoes back ``hub.challenge``
   after confirming ``hub.verify_token``.
2. **POST** event delivery — Messenger events wrapped in ``entry[].``.
   We normalize ``messages``, ``message_delivered`` and ``message_read``
   entries; everything else (``messaging_postbacks``, ``message_echo``,
   etc.) is ignored for now but can be added without touching services.

Verification uses HMAC-SHA1 of the raw body with the App Secret (the
``X-Hub-Signature-256`` header carries it as ``sha1=<hex>`` — Messenger
historically uses sha1).

See: https://developers.facebook.com/docs/messenger-platform/webhook
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
def verify(*, query_params: dict[str, str], body: bytes, headers: dict[str, str], app_secret: str, verify_token: str = "") -> tuple[bool, str]:
    """Validate a Facebook webhook request.

    For GET (subscription verification): checks ``hub.verify_token``
    against ``verify_token`` (the account's stored verify token) and
    returns ``(True, hub.challenge)``.
    For POST (event delivery): checks the ``X-Hub-Signature-256`` /
    ``X-Hub-Signature`` HMAC (using ``app_secret``) and returns ``(ok, "")``.
    """
    method_hint = (query_params.get("hub.mode") or "").lower()
    # Subscription handshake — compare against the verify token, NOT the
    # app secret. The verify token is a value the store owner picks when
    # subscribing the webhook; the app secret is only for HMAC signatures.
    if method_hint == "subscribe":
        token = query_params.get("hub.verify_token", "")
        if not verify_token or not hmac.compare_digest(token, verify_token):
            raise WebhookVerificationError("Facebook hub.verify_token mismatch.")
        return True, query_params.get("hub.challenge", "")

    # Event delivery — verify HMAC signature
    signature_header = headers.get("X-Hub-Signature-256") or headers.get("X-Hub-Signature") or ""
    if "=" in signature_header:
        algo, _, provided = signature_header.partition("=")
    else:
        provided = signature_header
        algo = "sha1"

    # Get the hash function - handle sha256, sha1, etc.
    algo_lower = algo.lower() if algo else "sha1"
    try:
        hash_func = getattr(hashlib, algo_lower)
    except AttributeError:
        logger.error("Facebook webhook verification failed: unsupported algorithm '%s'", algo)
        raise WebhookVerificationError(f"Facebook webhook signature verification failed: unsupported algorithm '{algo}'")

    expected = hmac.new(app_secret.encode("utf-8"), body, hash_func).hexdigest()
    logger.debug(
        "Facebook webhook signature verification: algorithm=%s, body_length=%d",
        algo, len(body)
    )
    if not provided or not hmac.compare_digest(provided, expected):
        logger.warning(
            "Facebook webhook signature mismatch: algorithm=%s, provided_prefix=%s, expected_prefix=%s",
            algo, provided[:10] if provided else "None", expected[:10]
        )
        raise WebhookVerificationError("Facebook webhook signature mismatch.")
    return True, ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse(*, body: bytes) -> list[NormalizedIncomingEvent | DeliveryUpdate]:
    """Parse a Facebook Messenger webhook body into normalized events.

    A single POST may contain multiple ``entry`` blocks (one per page)
    each with multiple ``messaging`` items. We flatten them into a list.
    Malformed entries are skipped with a warning rather than raising —
    one bad entry must not drop the whole batch.
    """
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WebhookParseError(f"Invalid Facebook webhook JSON: {exc}") from exc

    if payload.get("object") != "page":
        # Not a Messenger webhook (could be Instagram, etc.) — ignore.
        logger.debug("Ignoring non-page Facebook webhook object=%r", payload.get("object"))
        return []

    events: list[NormalizedIncomingEvent | DeliveryUpdate] = []
    for entry in payload.get("entry", []):
        for messaging in entry.get("messaging", []):
            try:
                events.extend(_parse_messaging(messaging))
            except Exception:  # pragma: no cover - defensive per-item
                logger.warning("Failed to parse FB messaging item: %s", messaging, exc_info=True)
    return events


def _parse_messaging(messaging: dict) -> list[NormalizedIncomingEvent | DeliveryUpdate]:
    """Parse a single ``messaging`` entry into zero or more events."""
    out: list[NormalizedIncomingEvent | DeliveryUpdate] = []
    sender_id = (messaging.get("sender") or {}).get("id", "")
    timestamp_ms = messaging.get("timestamp")

    # 1) Incoming message
    if "message" in messaging:
        msg = messaging["message"]
        external_id = msg.get("mid", "")
        text = msg.get("text", "")
        attachments = [_normalize_attachment(a) for a in msg.get("attachments", [])]
        location = _extract_location(msg.get("attachments", []))
        quick_replies = msg.get("quick_reply") or []
        # message_echo = the bot's own outbound echoed back; skip to avoid
        # duplicates (our outbound is recorded on send).
        if msg.get("is_echo"):
            return out

        out.append(
            NormalizedIncomingEvent(
                external_message_id=external_id,
                external_timestamp=_from_ms(timestamp_ms),
                sender_external_id=sender_id,
                message_type=_infer_message_type(text, attachments),
                text=text,
                attachments=[a for a in attachments if a],
                quick_replies=quick_replies if isinstance(quick_replies, list) else [],
                location=location,
                reply_to_external_id=(msg.get("reply_to") or {}).get("mid", ""),
                raw=messaging,
            )
        )
        return out

    # 2) Delivery receipt
    if "delivery" in messaging:
        delivery = messaging["delivery"]
        ids = delivery.get("mids", [])
        watermark = delivery.get("watermark")
        out.append(
            DeliveryUpdate(
                external_message_id=ids[0] if ids else "",
                status=DeliveryStatus.DELIVERED.value,
                timestamp=_from_ms(watermark),
                external_message_ids=ids,
                raw=messaging,
            )
        )
        return out

    # 3) Read receipt
    if "read" in messaging:
        read = messaging["read"]
        watermark = read.get("watermark")
        out.append(
            DeliveryUpdate(
                external_message_id="",
                status=DeliveryStatus.READ.value,
                timestamp=_from_ms(watermark),
                raw=messaging,
            )
        )
        return out

    # postbacks, typing, etc. are ignored for now.
    return out


# ---------------------------------------------------------------------------
# Attachment / message-type helpers
# ---------------------------------------------------------------------------
def _normalize_attachment(raw: dict) -> NormalizedAttachment | None:
    """Map a FB attachment to a NormalizedAttachment."""
    if not raw:
        return None
    payload = raw.get("payload") or {}
    atype = (raw.get("type") or "").lower()
    type_map = {
        "image": AttachmentType.IMAGE.value,
        "audio": AttachmentType.AUDIO.value,
        "video": AttachmentType.VIDEO.value,
        "file": AttachmentType.FILE.value,
        "fallback": AttachmentType.OTHER.value,
    }
    return NormalizedAttachment(
        attachment_type=type_map.get(atype, AttachmentType.OTHER.value),
        external_id=str(payload.get("attachment_id") or payload.get("sticker_id") or ""),
        external_url=payload.get("url") or "",
        file_name=payload.get("title") or "",
        extra=raw,
    )


def _extract_location(attachments: list[dict]) -> dict | None:
    """Pull a lat/lng dict from a location attachment, if present."""
    for a in attachments or []:
        if (a.get("type") or "").lower() == "location":
            coords = (a.get("payload") or {}).get("coordinates") or {}
            if coords:
                return {
                    "latitude": coords.get("lat"),
                    "longitude": coords.get("long"),
                }
    return None


def _infer_message_type(text: str, attachments: list) -> str:
    """Infer MessageType from FB message content."""
    if attachments:
        first_type = attachments[0].attachment_type if attachments else AttachmentType.FILE.value
        if first_type == AttachmentType.IMAGE.value:
            # FB stickers arrive as image attachments with a sticker_id.
            return MessageType.STICKER.value if attachments[0].extra.get("type") == "image" and (attachments[0].extra.get("payload") or {}).get("sticker_id") else MessageType.IMAGE.value
        return {
            AttachmentType.AUDIO.value: MessageType.AUDIO.value,
            AttachmentType.VIDEO.value: MessageType.VIDEO.value,
            AttachmentType.FILE.value: MessageType.FILE.value,
            AttachmentType.DOCUMENT.value: MessageType.DOCUMENT.value,
        }.get(first_type, MessageType.OTHER.value)
    if text:
        return MessageType.TEXT.value
    return MessageType.OTHER.value


def _from_ms(ms) -> datetime | None:
    """Convert a millisecond epoch (FB timestamps) to an aware datetime."""
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
