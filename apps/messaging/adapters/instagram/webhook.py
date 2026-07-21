"""
Instagram Direct webhook parsing & verification.

Instagram DMs are delivered through Meta's Messenger Platform, so the
webhook envelope is **identical in shape** to Facebook's:

    {
      "object": "instagram",          # <-- "page" for Facebook
      "entry": [{
        "id": "<ig-user-id>",
        "time": 1700000000000,
        "messaging": [{
          "sender":    {"id": "<igsid>"},
          "recipient": {"id": "<ig-user-id>"},
          "timestamp": 1700000000000,
          "message":   {"mid": "...", "text": "..."}
        }]
      }]
    }

The differences from Facebook's webhook are:

1. ``object == "instagram"`` (not ``"page"``).
2. Sender ids are **IGSIDs** (Instagram-scoped ids), not PSIDs.
3. ``message_echo``, ``reaction``, ``delivery`` and ``read`` payloads
   have the same field names as Facebook's.

Verification is HMAC-SHA1/SHA256 of the raw body with the App Secret
via the ``X-Hub-Signature-256`` / ``X-Hub-Signature`` header — same as
Facebook.

See: https://developers.facebook.com/docs/messenger-platform/instagram
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
def verify(
    *,
    query_params: dict[str, str],
    body: bytes,
    headers: dict[str, str],
    app_secret: str,
    verify_token: str = "",
) -> tuple[bool, str]:
    """Validate an Instagram webhook request.

    For GET (subscription verification): checks ``hub.verify_token``
    against ``verify_token`` (the account's stored verify token) and
    returns ``(True, hub.challenge)``.

    For POST (event delivery): checks the ``X-Hub-Signature-256`` /
    ``X-Hub-Signature`` HMAC (signed with ``app_secret``) and returns
    ``(ok, "")``.
    """
    mode = (query_params.get("hub.mode") or "").lower()

    # Subscription handshake — compare against the verify token.
    if mode == "subscribe":
        token = query_params.get("hub.verify_token", "")
        if not verify_token or not hmac.compare_digest(token, verify_token):
            raise WebhookVerificationError("Instagram hub.verify_token mismatch.")
        return True, query_params.get("hub.challenge", "")

    # Event delivery — verify HMAC signature.
    signature_header = (
        headers.get("X-Hub-Signature-256")
        or headers.get("X-Hub-Signature")
        or headers.get("x-hub-signature-256")
        or headers.get("x-hub-signature")
        or ""
    )
    if "=" in signature_header:
        algo, _, provided = signature_header.partition("=")
    else:
        provided = signature_header
        algo = "sha1"

    algo_lower = (algo or "sha1").lower()
    try:
        hash_func = getattr(hashlib, algo_lower)
    except AttributeError:
        logger.error("Instagram webhook verification failed: unsupported algorithm '%s'", algo)
        raise WebhookVerificationError(
            f"Instagram webhook signature verification failed: unsupported algorithm '{algo}'"
        ) from None

    expected = hmac.new(app_secret.encode("utf-8"), body, hash_func).hexdigest()
    if not provided or not hmac.compare_digest(provided, expected):
        logger.warning(
            "Instagram webhook signature mismatch: algorithm=%s, "
            "provided_prefix=%s, expected_prefix=%s",
            algo,
            provided[:10] if provided else "None",
            expected[:10],
        )
        raise WebhookVerificationError("Instagram webhook signature mismatch.")
    return True, ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse(*, body: bytes) -> list[NormalizedIncomingEvent | DeliveryUpdate]:
    """Parse an Instagram webhook body into normalized events.

    A single POST may contain multiple ``entry`` blocks (one per IG
    account) each with multiple ``messaging`` items. We flatten them
    into a list. Malformed entries are skipped with a warning rather
    than raising — one bad entry must not drop the whole batch.
    """
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WebhookParseError(f"Invalid Instagram webhook JSON: {exc}") from exc

    if payload.get("object") != "instagram":
        # Not an Instagram webhook (could be Facebook, WhatsApp, etc.).
        logger.debug("Ignoring non-instagram webhook object=%r", payload.get("object"))
        return []

    events: list[NormalizedIncomingEvent | DeliveryUpdate] = []
    for entry in payload.get("entry", []):
        for messaging in entry.get("messaging", []):
            try:
                events.extend(_parse_messaging(messaging))
            except Exception:  # pragma: no cover - defensive per-item
                logger.warning("Failed to parse IG messaging item: %s", messaging, exc_info=True)
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
        attachments = [
            a for a in (_normalize_attachment(a) for a in msg.get("attachments", [])) if a
        ]
        quick_replies = msg.get("quick_reply") or []

        # message_echo = the bot's own outbound echoed back; skip to
        # avoid duplicates (our outbound is recorded on send).
        if msg.get("is_echo"):
            logger.debug(
                "Skipping echo message from Instagram: mid=%s, text=%s",
                external_id,
                text[:50],
            )
            return out

        out.append(
            NormalizedIncomingEvent(
                external_message_id=external_id,
                external_timestamp=_from_ms(timestamp_ms),
                sender_external_id=sender_id,
                message_type=_infer_message_type(text, attachments),
                text=text,
                attachments=attachments,
                quick_replies=quick_replies if isinstance(quick_replies, list) else [],
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
    """Map an IG attachment to a NormalizedAttachment."""
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


def _infer_message_type(text: str, attachments: list) -> str:
    """Infer MessageType from IG message content."""
    if attachments:
        first_type = attachments[0].attachment_type if attachments else AttachmentType.FILE.value
        return {
            AttachmentType.IMAGE.value: MessageType.IMAGE.value,
            AttachmentType.AUDIO.value: MessageType.AUDIO.value,
            AttachmentType.VIDEO.value: MessageType.VIDEO.value,
            AttachmentType.FILE.value: MessageType.FILE.value,
            AttachmentType.DOCUMENT.value: MessageType.DOCUMENT.value,
        }.get(first_type, MessageType.OTHER.value)
    if text:
        return MessageType.TEXT.value
    return MessageType.OTHER.value


def _from_ms(ms) -> datetime | None:
    """Convert a millisecond epoch to an aware datetime."""
    if ms is None:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000.0, tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
