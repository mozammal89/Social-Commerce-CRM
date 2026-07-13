"""
Normalized data transfer objects for the messaging system.

These dataclasses are the **only** shape the service layer understands.
Every platform adapter is responsible for translating its proprietary
webhook/send payloads into these normalized structures and out of them
again. Services therefore never see ``messaging[0].message.text`` style
platform JSON — they operate on ``NormalizedIncomingEvent`` /
``OutboundMessage`` regardless of whether the channel is Facebook,
WhatsApp, or a future platform.

Keeping this translation at the adapter boundary is what makes the core
channel-agnostic: adding Instagram or Telegram later means writing a new
``parse_webhook`` for that platform, with zero changes to services or
models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..constants import AttachmentType, DeliveryStatus, MessageType


# ---------------------------------------------------------------------------
# Inbound (platform -> CRM)
# ---------------------------------------------------------------------------
@dataclass
class NormalizedAttachment:
    """A single media attachment on an incoming message."""

    attachment_type: str = AttachmentType.FILE.value
    external_id: str = ""
    external_url: str = ""
    mime_type: str = ""
    file_name: str = ""
    file_size: int | None = None
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    thumbnail_url: str = ""
    # Platform-specific extras the adapter couldn't map to a named
    # field (e.g. FB sticker_id). Preserved verbatim for completeness.
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizedIncomingEvent:
    """One inbound message, normalized from any platform's webhook.

    A platform webhook that bundles multiple messages yields several
    ``NormalizedIncomingEvent`` instances (one per message). The
    ``MessageService.ingest_normalized`` flow keys on ``external_id``
    for idempotency: the same event delivered twice is stored once.
    """

    # Identity -------------------------------------------------------------
    external_message_id: str          # Platform's message id (idempotency key)
    external_timestamp: datetime | None  # When the platform says it was sent

    # Who ------------------------------------------------------------------
    sender_external_id: str           # Customer's id on this channel (PSID/phone)
    sender_display_name: str = ""
    sender_avatar_url: str = ""
    # Optional rich profile the platform provided (FB profile fetch, WA
    # contact name). CustomerService uses it to enrich the profile.
    sender_profile: dict[str, Any] = field(default_factory=dict)

    # What -----------------------------------------------------------------
    message_type: str = MessageType.TEXT.value
    text: str = ""
    attachments: list[NormalizedAttachment] = field(default_factory=list)
    # Ephemeral interactive options shown alongside the message.
    quick_replies: list[dict[str, Any]] = field(default_factory=list)
    # Location payload (lat/lng) for ``MessageType.LOCATION``.
    location: dict[str, Any] | None = None

    # Context --------------------------------------------------------------
    reply_to_external_id: str = ""    # External id of the message this replies to

    # The original platform payload, kept for debugging / re-processing.
    # Services never read this; it is stored verbatim on Message.raw_payload.
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_content(self) -> bool:
        """True if the event carries any user-visible content."""
        return bool(self.text or self.attachments or self.location)


@dataclass
class DeliveryUpdate:
    """A delivery/read receipt for an earlier-sent or received message.

    Adapters parse status webhooks (FB ``message_delivered`` /
    ``message_read``; WA ``delivered``/``read``) into this shape. The
    service layer updates the matching ``Message.delivery_status`` and
    its timestamp fields.
    """

    external_message_id: str
    status: str                       # DeliveryStatus value
    timestamp: datetime | None = None
    # Some platforms batch receipts: a list of message ids affected.
    external_message_ids: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Outbound (CRM -> platform)
# ---------------------------------------------------------------------------
@dataclass
class OutboundAttachment:
    """An attachment to send outwards. Either a file path/bytes or a URL."""

    attachment_type: str = AttachmentType.FILE.value
    # One of: a local FileField path, raw bytes (with ``file_name``), or a
    # remote ``url`` the platform can fetch. Adapters pick what applies.
    file: Any = None
    file_name: str = ""
    url: str = ""
    mime_type: str = ""
    caption: str = ""


@dataclass
class OutboundMessage:
    """The normalized shape services hand to adapters to send.

    Built by ``MessageService.send`` from CRM user input (REST/WS) and
    translated by the adapter into the platform's send-API payload.
    """

    recipient_external_id: str        # Customer's channel id (PSID/phone)
    message_type: str = MessageType.TEXT.value
    text: str = ""
    attachments: list[OutboundAttachment] = field(default_factory=list)
    # Optional: send a pre-approved template (WhatsApp HSM, FB reusable).
    template_name: str = ""
    template_language: str = ""
    template_variables: dict[str, Any] = field(default_factory=dict)
    # If replying within a thread, some platforms accept a context id.
    reply_to_external_id: str = ""
    # Free-form adapter hints (e.g. FB messaging_type).
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def has_content(self) -> bool:
        return bool(self.text or self.attachments or self.template_name)


# ---------------------------------------------------------------------------
# Send result
# ---------------------------------------------------------------------------
@dataclass
class SendResult:
    """Outcome of an outbound send, returned by ``adapter.send_message``.

    * ``success`` — whether the platform accepted the send.
    * ``external_id`` — the platform-assigned message id (for delivery
      tracking & dedupe). ``None`` when the platform doesn't return one
      synchronously.
    * ``status`` — the ``DeliveryStatus`` the message should be set to
      (typically SENT on success, FAILED on error).
    * ``error_code`` / ``error_message`` — populated on failure.
    """

    success: bool
    external_id: str | None = None
    status: str = DeliveryStatus.SENT.value
    error_code: str = ""
    error_message: str = ""
    # The platform's raw response, for debugging.
    raw: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Credential verification result
# ---------------------------------------------------------------------------
@dataclass
class VerifyResult:
    """Outcome of a credential check against the platform.

    Returned by ``adapter.verify_credentials(account)``. The service layer
    uses it to set the connected-account's status (``connected`` vs
    ``error``) and surface a friendly error message to the UI.

    * ``valid`` — whether the credentials work against the platform.
    * ``account_name`` — the page/number name reported back by the
      platform (used to auto-fill the display name when valid).
    * ``external_id`` — the platform-confirmed account id (may differ from
      what the user entered; the service keeps the user-entered value but
      records the discrepancy in ``raw``).
    * ``error_code`` / ``error_message`` — populated on failure.
    """

    valid: bool
    account_name: str = ""
    external_id: str = ""
    error_message: str = ""
    error_code: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
