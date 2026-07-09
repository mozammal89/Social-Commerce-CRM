"""
Stable enums and identifiers for the omnichannel messaging system.

These values are referenced by models, adapters, services, fixtures,
seeders and tests. Renaming a value here is a breaking change for
stored rows and webhook idempotency keys, so treat them as frozen
public identifiers once released.
"""

from __future__ import annotations

from django.db import models


# ---------------------------------------------------------------------------
# Channels — the messaging platforms the deployment can talk to.
#
# ``ChannelType`` is the *category* of platform (messenger, whatsapp).
# The global ``Channel`` catalog rows add a unique ``slug`` per concrete
# channel (e.g. ``facebook-messenger``) so multiple accounts of the same
# type are still distinguishable. Adding a new platform is a new entry
# here plus an adapter that declares ``channel_type``.
# ---------------------------------------------------------------------------
class ChannelType(models.TextChoices):
    FACEBOOK_MESSENGER = "facebook_messenger", "Facebook Messenger"
    WHATSAPP = "whatsapp", "WhatsApp"
    INSTAGRAM = "instagram", "Instagram"
    TELEGRAM = "telegram", "Telegram"
    EMAIL = "email", "Email"
    SMS = "sms", "SMS"
    TIKTOK = "tiktok", "TikTok"
    LIVE_CHAT = "live_chat", "Live Chat"
    OTHER = "other", "Other"


# ---------------------------------------------------------------------------
# ConnectedAccount lifecycle.
# ---------------------------------------------------------------------------
class ConnectedAccountStatus(models.TextChoices):
    PENDING = "pending", "Pending"            # OAuth flow started, not yet authorized
    CONNECTED = "connected", "Connected"      # Fully authorized & usable
    DISCONNECTED = "disconnected", "Disconnected"  # Disabled by the store owner
    ERROR = "error", "Error"                  # Repeated API failures / needs attention
    EXPIRED = "expired", "Expired"            # Token revoked or expired


# ---------------------------------------------------------------------------
# Conversations.
# ---------------------------------------------------------------------------
class ConversationStatus(models.TextChoices):
    OPEN = "open", "Open"            # Actively being handled
    PENDING = "pending", "Pending"  # Awaiting customer reply
    RESOLVED = "resolved", "Resolved"  # Agent considers it done
    CLOSED = "closed", "Closed"      # Archived, no further action
    SPAM = "spam", "Spam"


# Statuses that count as "active" — used for the partial unique
# constraint that keeps one active conversation per (account, customer).
ACTIVE_CONVERSATION_STATUSES = (
    ConversationStatus.OPEN.value,
    ConversationStatus.PENDING.value,
)


class ConversationPriority(models.TextChoices):
    URGENT = "urgent", "Urgent"
    HIGH = "high", "High"
    NORMAL = "normal", "Normal"
    LOW = "low", "Low"


# ---------------------------------------------------------------------------
# Messages.
# ---------------------------------------------------------------------------
class MessageDirection(models.TextChoices):
    INBOUND = "inbound", "Inbound"    # customer -> business
    OUTBOUND = "outbound", "Outbound"  # business -> customer


class SenderType(models.TextChoices):
    CUSTOMER = "customer", "Customer"
    AGENT = "agent", "Agent"          # A human team member
    SYSTEM = "system", "System"       # Automated / platform-generated
    BOT = "bot", "Bot"                # Rule-based or AI responder


class MessageType(models.TextChoices):
    TEXT = "text", "Text"
    IMAGE = "image", "Image"
    AUDIO = "audio", "Audio"
    VIDEO = "video", "Video"
    DOCUMENT = "document", "Document"
    FILE = "file", "File"
    STICKER = "sticker", "Sticker"
    TEMPLATE = "template", "Template"      # Pre-approved message template
    LOCATION = "location", "Location"
    BUTTONS = "buttons", "Buttons"          # Interactive button payload
    QUICK_REPLY = "quick_reply", "Quick Reply"
    SYSTEM = "system", "System"            # e.g. "X started a chat"
    REACTION = "reaction", "Reaction"
    OTHER = "other", "Other"


class DeliveryStatus(models.TextChoices):
    PENDING = "pending", "Pending"          # Queued / not yet handed to platform
    SENT = "sent", "Sent"                    # Platform accepted the send
    DELIVERED = "delivered", "Delivered"     # Reached the recipient device
    READ = "read", "Read"                    # Recipient opened it
    FAILED = "failed", "Failed"             # Permanent failure
    UNDELIVERED = "undelivered", "Undelivered"  # Platform couldn't deliver


class AttachmentType(models.TextChoices):
    IMAGE = "image", "Image"
    AUDIO = "audio", "Audio"
    VIDEO = "video", "Video"
    DOCUMENT = "document", "Document"
    FILE = "file", "File"
    THUMBNAIL = "thumbnail", "Thumbnail"
    OTHER = "other", "Other"


# ---------------------------------------------------------------------------
# Message templates (WhatsApp HSM, FB reusable content, ...).
# ---------------------------------------------------------------------------
class MessageTemplateStatus(models.TextChoices):
    DRAFT = "draft", "Draft"
    PENDING = "pending", "Pending"          # Submitted for platform approval
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


# ---------------------------------------------------------------------------
# Activity feed — powers the unified customer timeline + audit trail.
#
# Convention: "<entity>.<verb>", mirroring the RBAC audit-action style
# in apps.permissions.constants so the two audit styles read alike.
# ---------------------------------------------------------------------------
class ActivityType(models.TextChoices):
    CONVERSATION_CREATED = "conversation.created", "Conversation created"
    CONVERSATION_STATUS_CHANGED = "conversation.status_changed", "Status changed"
    CONVERSATION_ASSIGNED = "conversation.assigned", "Conversation assigned"
    CONVERSATION_UNASSIGNED = "conversation.unassigned", "Conversation unassigned"
    CONVERSATION_PRIORITY_CHANGED = "conversation.priority_changed", "Priority changed"
    MESSAGE_RECEIVED = "message.received", "Message received"
    MESSAGE_SENT = "message.sent", "Message sent"
    MESSAGE_FAILED = "message.failed", "Message failed"
    NOTE_ADDED = "note.added", "Internal note added"
    NOTE_UPDATED = "note.updated", "Internal note updated"
    CUSTOMER_CREATED = "customer.created", "Customer created"
    CUSTOMER_UPDATED = "customer.updated", "Customer profile updated"
    CUSTOMER_MERGED = "customer.merged", "Customer merged"
    TAG_ADDED = "tag.added", "Tag added"
    TAG_REMOVED = "tag.removed", "Tag removed"
    CHANNEL_CONNECTED = "channel.connected", "Channel connected"
    CHANNEL_DISCONNECTED = "channel.disconnected", "Channel disconnected"


# Convenience grouping for the timeline UI.
MESSAGE_ACTIVITY_TYPES = (
    ActivityType.MESSAGE_RECEIVED.value,
    ActivityType.MESSAGE_SENT.value,
    ActivityType.MESSAGE_FAILED.value,
)


# ---------------------------------------------------------------------------
# Channel capability flags. Stored on the global ``Channel`` catalog as
# ``capabilities`` (JSONField). Adapters declare what the platform can do;
# the UI/services degrade gracefully when a capability is absent.
# ---------------------------------------------------------------------------
class ChannelCapability:
    """String constants for capability flags (not a DB enum)."""

    TEXT = "text"
    IMAGES = "images"
    AUDIO = "audio"
    VIDEO = "video"
    DOCUMENTS = "documents"
    STICKERS = "stickers"
    LOCATION = "location"
    TEMPLATES = "templates"
    QUICK_REPLIES = "quick_replies"
    BUTTONS = "buttons"
    REACTIONS = "reactions"
    TYPING_INDICATOR = "typing_indicator"
    READ_RECEIPTS = "read_receipts"
    DELIVERY_STATUS = "delivery_status"
    FILE_UPLOADS = "file_uploads"


# Default capability sets per built-in channel, used by ``sync_channels``.
DEFAULT_CAPABILITIES = {
    "facebook-messenger": [
        ChannelCapability.TEXT, ChannelCapability.IMAGES, ChannelCapability.AUDIO,
        ChannelCapability.VIDEO, ChannelCapability.DOCUMENTS, ChannelCapability.STICKERS,
        ChannelCapability.LOCATION, ChannelCapability.QUICK_REPLIES, ChannelCapability.BUTTONS,
        ChannelCapability.TEMPLATES, ChannelCapability.TYPING_INDICATOR,
        ChannelCapability.READ_RECEIPTS, ChannelCapability.DELIVERY_STATUS,
    ],
    "whatsapp": [
        ChannelCapability.TEXT, ChannelCapability.IMAGES, ChannelCapability.AUDIO,
        ChannelCapability.VIDEO, ChannelCapability.DOCUMENTS, ChannelCapability.STICKERS,
        ChannelCapability.LOCATION, ChannelCapability.TEMPLATES, ChannelCapability.BUTTONS,
        ChannelCapability.READ_RECEIPTS, ChannelCapability.DELIVERY_STATUS,
    ],
}


# ---------------------------------------------------------------------------
# Default catalog channels seeded by data migrations / ``sync_channels``.
# Keep these in sync with the adapter classes in ``apps/messaging/adapters``.
# ---------------------------------------------------------------------------
DEFAULT_CHANNELS = [
    {
        "slug": "facebook-messenger",
        "channel_type": ChannelType.FACEBOOK_MESSENGER.value,
        "name": "Facebook Messenger",
        "adapter_class": "apps.messaging.adapters.facebook.adapter.FacebookAdapter",
        "sort_order": 10,
    },
    {
        "slug": "whatsapp",
        "channel_type": ChannelType.WHATSAPP.value,
        "name": "WhatsApp Business",
        "adapter_class": "apps.messaging.adapters.whatsapp.adapter.WhatsAppAdapter",
        "sort_order": 20,
    },
]
