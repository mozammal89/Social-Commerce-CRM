"""
Telegram Bot API webhook parsing & verification.

Telegram's webhook model differs from Facebook's / WhatsApp's in three
important ways:

1. **No GET subscription handshake.** The webhook is registered by the
   adapter calling ``setWebhook`` out-of-band; Telegram only ever POSTs
   ``Update`` objects to the configured URL. Our generic dispatcher
   still receives GET requests (e.g. for health probes), so ``verify``
   returns ``(False, "")`` for them — the dispatcher maps that to a 403.

2. **Optional HMAC-less secret-token verification.** When the bot was
   registered with ``secret_token``, every webhook POST carries that
   token in the ``X-Telegram-Bot-Api-Secret-Token`` header. We compare
   it (constant-time) against the account's stored secret. When no
   secret is configured on the account, verification is skipped — this
   is still safe-ish because the webhook URL embeds a random
   ``account_id`` UUID and is HTTPS-only.

3. **The payload is a single ``Update`` object**, not a batched entry
   array. Each ``update_id`` is unique and processed once. The top-level
   key (``message``, ``edited_message``, ``channel_post``,
   ``callback_query``) tells us what happened.

A ``message`` Update looks like::

    {
      "update_id": 12345,
      "message": {
        "message_id": 42,
        "from": {"id": 111, "is_bot": false,
                 "first_name": "Ada", "last_name": "Lovelace",
                 "username": "ada", "language_code": "en"},
        "chat": {"id": 111, "type": "private",
                 "first_name": "Ada", "username": "ada"},
        "date": 1700000000,
        "text": "Hello"
      }
    }

See: https://core.telegram.org/bots/api#making-requests
     https://core.telegram.org/bots/api#update
"""

from __future__ import annotations

import hmac
import json
import logging
from datetime import datetime, timezone

from ..dto import DeliveryUpdate, NormalizedAttachment, NormalizedIncomingEvent
from ..exceptions import WebhookParseError, WebhookVerificationError
from ...constants import AttachmentType, MessageType

logger = logging.getLogger(__name__)

# Header name Telegram uses for the optional webhook secret. Telegram
# sends this exact case, but we do a case-insensitive scan of the
# incoming headers below to be defensive.
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


# ---------------------------------------------------------------------------
# Verification
# ---------------------------------------------------------------------------
def verify(
    *,
    method: str,
    query_params: dict[str, str],
    body: bytes,
    headers: dict[str, str],
    secret_token: str = "",
) -> tuple[bool, str]:
    """Validate a Telegram webhook request.

    * GET  → always ``(False, "")``. Telegram does not handshake.
    * POST → if a ``secret_token`` is configured on the account, the
      request MUST carry it in the ``X-Telegram-Bot-Api-Secret-Token``
      header (constant-time compared). Without a configured secret we
      skip verification (the webhook URL embeds a per-account UUID and
      is HTTPS-only) and accept the POST.
    """
    if method.upper() == "GET":
        # Telegram never sends GETs to a webhook — refuse so the
        # dispatcher returns 403 and the platform doesn't retry.
        return False, ""

    # Case-insensitive header lookup (Django's request.headers dict is
    # already case-insensitive, but the adapters are sometimes called
    # with a raw dict — e.g. in tests — so normalize here).
    provided = ""
    for k, v in (headers or {}).items():
        if k.lower() == SECRET_HEADER.lower():
            provided = v
            break

    if not secret_token:
        # No secret configured — fall through and accept the POST. This
        # is the legacy behavior and keeps existing setups working.
        return True, ""

    if not provided or not hmac.compare_digest(str(provided), str(secret_token)):
        logger.warning(
            "Telegram webhook secret_token mismatch: provided_prefix=%s",
            provided[:10] if provided else "None",
        )
        raise WebhookVerificationError("Telegram webhook secret_token mismatch.")
    return True, ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def parse(*, body: bytes) -> list[NormalizedIncomingEvent | DeliveryUpdate]:
    """Parse a Telegram ``Update`` object into normalized events.

    Telegram sends one Update per POST. We currently normalize:

    * ``message`` / ``edited_message`` / ``channel_post``  → inbound
      text/media/location message.
    * ``callback_query``                                  → button tap,
      surfaced as a ``NormalizedIncomingEvent`` carrying the button
      payload as text (so the agent sees the click in the thread).

    Other update types (``inline_query``, ``poll``, ``my_chat_member``,
    etc.) are ignored. As everywhere else, parse errors per-item are
    skipped with a warning rather than raising.
    """
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise WebhookParseError(f"Invalid Telegram webhook JSON: {exc}") from exc

    if not isinstance(payload, dict):
        logger.debug("Ignoring non-object Telegram webhook payload")
        return []

    events: list[NormalizedIncomingEvent | DeliveryUpdate] = []

    # Telegram's primary inbound: a private/group message.
    for key in ("message", "edited_message", "channel_post"):
        msg = payload.get(key)
        if isinstance(msg, dict):
            try:
                parsed = _parse_message(msg)
                if parsed is not None:
                    events.append(parsed)
            except Exception:  # pragma: no cover - defensive per-item
                logger.warning("Failed to parse Telegram %s: %s", key, msg, exc_info=True)

    # callback_query = a tap on an inline-keyboard button. Surface as
    # a text message so the agent sees what the customer clicked.
    cq = payload.get("callback_query")
    if isinstance(cq, dict):
        try:
            parsed = _parse_callback_query(cq)
            if parsed is not None:
                events.append(parsed)
        except Exception:  # pragma: no cover - defensive per-item
            logger.warning("Failed to parse Telegram callback_query: %s", cq, exc_info=True)

    return events


def _parse_message(msg: dict) -> NormalizedIncomingEvent | None:
    """Normalize a Telegram ``message`` object.

    Returns ``None`` for items we deliberately ignore (e.g. service
    messages with no ``from``/``chat``).
    """
    message_id = msg.get("message_id")
    if message_id is None:
        return None

    sender = msg.get("from") or {}
    chat = msg.get("chat") or {}
    # For private chats, ``chat.id == from.id``. For groups, ``chat.id``
    # is the group's id and ``from.id`` is the user who spoke. We track
    # customers by the user's Telegram id, but reply to ``chat.id``.
    sender_id = str(sender.get("id") or chat.get("id") or "")
    if not sender_id:
        return None

    timestamp = _from_epoch(msg.get("date"))
    # Telegram's message ids are unique per-chat, not globally. Prefix
    # with the chat id to make the (idempotency) key globally unique.
    chat_id = str(chat.get("id") or "")
    external_id = f"tg:{chat_id}:{message_id}" if chat_id else f"tg:{message_id}"

    text = msg.get("text") or msg.get("caption") or ""
    attachments: list[NormalizedAttachment] = []
    location: dict | None = None
    message_type = MessageType.TEXT.value

    # Media: Telegram uses one top-level field per media type. We
    # check them in order and pick the first present one.
    if "photo" in msg:
        # ``photo`` is a list of progressively-larger thumbnails; pick
        # the largest (last) entry. ``file_id`` is the Bot-API media id.
        photos = msg.get("photo") or []
        largest = photos[-1] if photos else {}
        attachments.append(
            NormalizedAttachment(
                attachment_type=AttachmentType.IMAGE.value,
                external_id=largest.get("file_id", ""),
                file_size=largest.get("file_size"),
                width=largest.get("width"),
                height=largest.get("height"),
                extra={"photo_sizes": photos},
            )
        )
        message_type = MessageType.IMAGE.value
    elif "sticker" in msg:
        st = msg.get("sticker") or {}
        attachments.append(
            NormalizedAttachment(
                attachment_type=AttachmentType.IMAGE.value,
                external_id=st.get("file_id", ""),
                width=st.get("width"),
                height=st.get("height"),
                file_size=st.get("file_size"),
                thumbnail_url=(st.get("thumb") or {}).get("file_url", ""),
                extra={**st, "emoji": st.get("emoji", "")},
            )
        )
        message_type = MessageType.STICKER.value
    elif "voice" in msg or "audio" in msg:
        block = msg.get("voice") or msg.get("audio") or {}
        attachments.append(
            NormalizedAttachment(
                attachment_type=AttachmentType.AUDIO.value,
                external_id=block.get("file_id", ""),
                mime_type=block.get("mime_type", ""),
                duration=block.get("duration"),
                extra=block,
            )
        )
        message_type = MessageType.AUDIO.value
    elif "video" in msg or "animation" in msg:
        block = msg.get("video") or msg.get("animation") or {}
        attachments.append(
            NormalizedAttachment(
                attachment_type=AttachmentType.VIDEO.value,
                external_id=block.get("file_id", ""),
                mime_type=block.get("mime_type", ""),
                duration=block.get("duration"),
                width=block.get("width"),
                height=block.get("height"),
                extra=block,
            )
        )
        message_type = MessageType.VIDEO.value
    elif "document" in msg:
        block = msg.get("document") or {}
        attachments.append(
            NormalizedAttachment(
                attachment_type=AttachmentType.DOCUMENT.value,
                external_id=block.get("file_id", ""),
                mime_type=block.get("mime_type", ""),
                file_name=block.get("file_name", ""),
                file_size=block.get("file_size"),
                extra=block,
            )
        )
        message_type = MessageType.DOCUMENT.value
    elif "location" in msg:
        loc = msg.get("location") or {}
        location = {
            "latitude": loc.get("latitude"),
            "longitude": loc.get("longitude"),
        }
        message_type = MessageType.LOCATION.value
    elif "contact" in msg:
        # Telegram shares contacts as a structured payload; surface the
        # phone number as text so it's visible in the inbox.
        c = msg.get("contact") or {}
        text = c.get("phone_number", "") or text
        message_type = MessageType.OTHER.value

    # Display name — prefer first/last name, fall back to @username.
    first = sender.get("first_name", "")
    last = sender.get("last_name", "")
    full = f"{first} {last}".strip()
    username = sender.get("username", "")
    display = full or (f"@{username}" if username else "")

    # Reply context — Telegram uses ``reply_to_message.message_id``.
    reply_to = ""
    rtm = msg.get("reply_to_message")
    if isinstance(rtm, dict) and rtm.get("message_id") is not None:
        reply_to = f"tg:{chat_id}:{rtm['message_id']}" if chat_id else f"tg:{rtm['message_id']}"

    # Sender profile snapshot (used by CustomerService for enrichment).
    profile = {
        "first_name": first,
        "last_name": last,
        "username": username,
        "language_code": sender.get("language_code", ""),
    }

    return NormalizedIncomingEvent(
        external_message_id=external_id,
        external_timestamp=timestamp,
        sender_external_id=sender_id,
        sender_display_name=display,
        sender_profile=profile,
        message_type=message_type,
        text=text,
        attachments=attachments,
        location=location,
        reply_to_external_id=reply_to,
        raw=msg,
    )


def _parse_callback_query(cq: dict) -> NormalizedIncomingEvent | None:
    """Normalize a Telegram ``callback_query`` (inline-button tap).

    The button's ``data`` payload is surfaced as the message text so the
    agent sees what the customer picked. The ``id`` field is unique per
    query and is used as the idempotency key.
    """
    cq_id = cq.get("id")
    if cq_id is None:
        return None

    sender = cq.get("from") or {}
    sender_id = str(sender.get("id") or "")
    if not sender_id:
        return None

    data = cq.get("data") or ""
    message = cq.get("message") or {}
    chat_id = str((message.get("chat") or {}).get("id") or "")
    external_id = f"tg:cb:{cq_id}"
    timestamp = _from_epoch(message.get("date"))

    first = sender.get("first_name", "")
    last = sender.get("last_name", "")
    display = f"{first} {last}".strip() or (
        f"@{sender.get('username', '')}" if sender.get("username") else ""
    )

    return NormalizedIncomingEvent(
        external_message_id=external_id,
        external_timestamp=timestamp,
        sender_external_id=sender_id,
        sender_display_name=display,
        sender_profile={
            "first_name": first,
            "last_name": last,
            "username": sender.get("username", ""),
            "language_code": sender.get("language_code", ""),
        },
        message_type=MessageType.BUTTONS.value,
        text=f"[button] {data}" if data else "[button]",
        reply_to_external_id=(
            f"tg:{chat_id}:{message.get('message_id')}"
            if chat_id and message.get("message_id") is not None
            else ""
        ),
        raw=cq,
    )


def _from_epoch(epoch) -> datetime | None:
    """Convert a Telegram second-precision epoch to an aware datetime."""
    if epoch is None:
        return None
    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None


__all__ = [
    "verify",
    "parse",
    "SECRET_HEADER",
]
