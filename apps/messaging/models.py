"""
Core models for the omnichannel messaging system.

Architecture
------------
This module defines a **channel-agnostic** messaging core. There are no
``FacebookMessage`` or ``WhatsAppMessage`` models anywhere: platform
specifics live exclusively behind adapters
(see ``apps/messaging/adapters/``). Services (``services.py``) consume
normalized dataclasses and never touch platform payloads directly.

Multi-tenancy
-------------
Every domain model inherits ``TenantBaseModel`` (UUID PK + timestamps +
soft-delete + a ``store`` FK) from ``apps.common.models``, so store
isolation is structural: a model row always belongs to exactly one
``Store``, and viewsets filter by ``request.store`` via the existing
``StoreScopedQuerysetMixin``. The only model *not* store-scoped is
``Channel`` — the global catalog of supported platforms, seeded once per
deployment.

Layout
------
* Connection layer — ``Channel``, ``ConnectedAccount``
* Customer layer   — ``Customer``, ``CustomerChannelIdentity``, ``CustomerTag``, ``CustomerNote``
* Conversation layer — ``Conversation``, ``Message``, ``Attachment``, ``InternalNote``
* Supporting        — ``Activity`` (unified timeline), ``MessageTemplate``, ``Reaction``
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.models import BaseModel, TenantBaseModel

from .constants import (
    ACTIVE_CONVERSATION_STATUSES,
    AttachmentType,
    ConnectedAccountStatus,
    ConversationPriority,
    ConversationStatus,
    DeliveryStatus,
    MessageDirection,
    MessageTemplateStatus,
    MessageType,
    SenderType,
)
from .fields import EncryptedJSONField


# ---------------------------------------------------------------------------
# Connection layer
# ---------------------------------------------------------------------------
class Channel(BaseModel):
    """Global catalog of messaging platforms the deployment supports.

    One row per platform (e.g. ``facebook-messenger``, ``whatsapp``).
    Seeded by data migrations / the ``sync_channels`` command. Adding
    Instagram or Telegram later is a new row here plus a matching
    adapter — no model changes. ``adapter_class`` is the dotted path to
    the adapter implementation; the service layer loads it lazily.
    """

    slug = models.SlugField(max_length=80, unique=True, db_index=True)
    channel_type = models.CharField(
        max_length=40,
        # ChannelType choices are defined here (not imported) to keep the
        # model self-contained for migrations.
        choices=[
            ("facebook_messenger", "Facebook Messenger"),
            ("whatsapp", "WhatsApp"),
            ("instagram", "Instagram"),
            ("telegram", "Telegram"),
            ("email", "Email"),
            ("sms", "SMS"),
            ("tiktok", "TikTok"),
            ("live_chat", "Live Chat"),
            ("other", "Other"),
        ],
        db_index=True,
    )
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    icon = models.CharField(
        max_length=64, blank=True, help_text=_("Icon name or emoji for the UI.")
    )
    is_enabled = models.BooleanField(default=True, db_index=True)
    capabilities = models.JSONField(
        default=dict,
        blank=True,
        help_text=_(
            "Capability flags the platform supports (text, images, audio, "
            "video, templates, reactions, typing_indicator, ...). See "
            "ChannelCapability constants."
        ),
    )
    adapter_class = models.CharField(
        max_length=255,
        blank=True,
        help_text=_(
            "Dotted path to the BaseChannelAdapter subclass, e.g. apps.messaging.adapters.facebook.adapter.FacebookAdapter"
        ),
    )
    config_schema = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Optional JSON schema describing per-account config fields."),
    )
    sort_order = models.IntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]
        db_table = "messaging_channel"
        indexes = [
            models.Index(fields=["is_enabled", "sort_order"]),
        ]

    def __str__(self) -> str:
        return self.name

    def has_capability(self, capability: str) -> bool:
        return capability in (self.capabilities or [])


class ConnectedAccount(TenantBaseModel):
    """A store's connection to one channel account.

    One Facebook Page = one row. One WhatsApp Business number = one row.
    Credentials (page access tokens, app secrets, signing secrets) are
    stored encrypted via ``EncryptedJSONField``. The ``(store, channel,
    external_id)`` tuple uniquely identifies an account: a store can
    connect many pages/numbers but not the same one twice.
    """

    channel = models.ForeignKey(
        Channel,
        on_delete=models.PROTECT,
        related_name="connected_accounts",
    )
    name = models.CharField(
        max_length=200,
        help_text=_("Human label, e.g. the page or number name."),
    )
    external_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text=_("Platform-side account id: FB Page id, WA phone_number_id / waba_id, ..."),
    )
    status = models.CharField(
        max_length=20,
        choices=ConnectedAccountStatus.choices,
        default=ConnectedAccountStatus.PENDING,
        db_index=True,
    )
    credentials = EncryptedJSONField(
        default=dict,
        blank=True,
        help_text=_("Encrypted OAuth tokens, app secrets, signing secrets, etc."),
    )
    metadata = models.JSONField(default=dict, blank=True)
    webhook_verify_token = models.CharField(
        max_length=255,
        blank=True,
        help_text=_("Token used to verify the platform's initial webhook subscription."),
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    connected_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="connected_messaging_accounts",
    )

    class Meta:
        ordering = ["-created_at"]
        db_table = "messaging_connected_account"
        constraints = [
            models.UniqueConstraint(
                fields=["store", "channel", "external_id"],
                name="uniq_connected_account_store_channel_external",
            ),
        ]
        indexes = [
            models.Index(fields=["store", "status"]),
            models.Index(fields=["store", "channel", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.channel.slug})"

    @property
    def is_active(self) -> bool:
        return self.status == ConnectedAccountStatus.CONNECTED


# ---------------------------------------------------------------------------
# Customer layer
# ---------------------------------------------------------------------------
class CustomerTag(TenantBaseModel):
    """A store-scoped label customers can be tagged with."""

    name = models.CharField(max_length=80)
    slug = models.SlugField(max_length=80)
    color = models.CharField(max_length=20, blank=True, help_text=_("Hex color for the UI."))

    class Meta:
        ordering = ["name"]
        db_table = "messaging_customer_tag"
        constraints = [
            models.UniqueConstraint(
                fields=["store", "name"],
                name="uniq_customer_tag_store_name",
            ),
            models.UniqueConstraint(
                fields=["store", "slug"],
                name="uniq_customer_tag_store_slug",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class Customer(TenantBaseModel):
    """A unified customer profile within a store.

    A single person may reach out via Messenger *and* WhatsApp; each
    channel contact creates a ``CustomerChannelIdentity`` linked back to
    this profile, so the inbox and timeline show one customer across
    channels. Profiles can be merged (``merged_into``) when duplicates
    are detected; the duplicate is then read-only.
    """

    first_name = models.CharField(max_length=120, blank=True)
    last_name = models.CharField(max_length=120, blank=True)
    display_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True, db_index=True)
    phone = models.CharField(max_length=40, blank=True, db_index=True)
    avatar = models.URLField(max_length=1024, blank=True)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_customers",
    )
    tags = models.ManyToManyField(
        CustomerTag,
        blank=True,
        related_name="customers",
    )
    notes = models.TextField(blank=True, help_text=_("Free-form notes on the customer."))
    metadata = models.JSONField(default=dict, blank=True)
    first_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_seen_at = models.DateTimeField(null=True, blank=True, db_index=True)

    # Merge support: a merged (duplicate) customer points at the
    # surviving profile. All identities/conversations/messages are
    # re-pointed at the primary on merge; the duplicate is kept for
    # historical reference and rendered read-only.
    is_merged = models.BooleanField(default=False, db_index=True)
    merged_into = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="merged_duplicates",
    )
    merged_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-last_seen_at", "-created_at"]
        db_table = "messaging_customer"
        constraints = [
            # Partial unique constraints enforce deterministic cross-channel
            # matching (Tier 2): at most one *active (un-merged)* customer per
            # (store, normalized email) and per (store, phone). Empty values
            # and merged duplicates are excluded so they don't collide.
            # NOTE: applying these fails if existing data already violates
            # them — migration 0003 pre-scans and reports violations before
            # adding the constraints so they can be merged first.
            models.UniqueConstraint(
                "store",
                Lower("email"),
                condition=~Q(email="") & Q(is_merged=False),
                name="uniq_customer_store_email_active",
            ),
            models.UniqueConstraint(
                "store",
                "phone",
                condition=~Q(phone="") & Q(is_merged=False),
                name="uniq_customer_store_phone_active",
            ),
        ]
        indexes = [
            models.Index(fields=["store", "last_seen_at"]),
            models.Index(fields=["store", "assigned_to"]),
            models.Index(fields=["store", "is_merged"]),
            models.Index(fields=["store", "email"]),
            models.Index(fields=["store", "phone"]),
        ]

    def __str__(self) -> str:
        return self.display_name or self.full_name or f"Customer {self.pk}"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def primary(self) -> "Customer":
        """Follow the merge chain to the surviving profile."""
        seen: set[uuid.UUID] = set()
        current = self
        while current.merged_into_id and current.merged_into_id not in seen:
            seen.add(current.id)
            current = current.merged_into
        return current


class CustomerChannelIdentity(TenantBaseModel):
    """How a customer is known on a specific channel.

    This is the resolution key for inbound webhooks: given a
    ``connected_account`` and the platform's sender id (FB PSID, WA
    phone number), look up (or create) the identity, then the customer.
    A customer may have multiple identities (one per channel/account).
    """

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="channel_identities",
    )
    connected_account = models.ForeignKey(
        ConnectedAccount,
        on_delete=models.CASCADE,
        related_name="customer_identities",
    )
    channel = models.ForeignKey(
        Channel,
        on_delete=models.PROTECT,
        related_name="customer_identities",
    )
    external_id = models.CharField(
        max_length=255,
        db_index=True,
        help_text=_("Platform-side id of the customer: FB PSID/ASID, WA phone number, ..."),
    )
    display_name = models.CharField(max_length=255, blank=True)
    avatar_url = models.URLField(max_length=1024, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    # --- Profile sync lifecycle (added to enable background profile refresh) ---
    # Channel-provided context that doesn't belong on the channel-agnostic
    # Customer profile. Filled by ``adapter.fetch_identity_profile()``.
    language = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text=_("ISO 639-1 language code from the channel, if exposed."),
    )
    timezone = models.CharField(
        max_length=50,
        blank=True,
        default="",
        help_text=_("IANA timezone (e.g. America/New_York) from the channel, if exposed."),
    )
    # When the identity's profile was last refreshed from the channel API.
    # NULL means "never synced" — the periodic refresh task picks those up
    # first. Drives the daily sync batch.
    last_synced_at = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
        help_text=_("Last successful profile refresh from the channel API."),
    )
    # UI hint: which identity's display_name/avatar should surface on the
    # customer card. Defaults to the first identity; user can change it.
    # Not a hard constraint — at most one is primary per customer is enforced
    # at the service layer, not the DB, to keep migrations simple.
    is_primary = models.BooleanField(
        default=False,
        help_text=_("Whether this identity's profile is surfaced on the customer card."),
    )
    # Last raw profile payload from the channel, kept separate from
    # ``metadata`` (which is adapter-controlled). Useful for debugging and
    # for the source-of-truth field tracking (see CustomerProfileService).
    profile_metadata = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Last raw profile payload from the channel + per-field source tracking."),
    )

    class Meta:
        ordering = ["-created_at"]
        db_table = "messaging_customer_channel_identity"
        constraints = [
            # One customer per (store, channel, external_id) so inbound
            # events deterministically resolve to a single profile.
            models.UniqueConstraint(
                fields=["store", "channel", "external_id"],
                name="uniq_customer_identity_store_channel_external",
            ),
        ]
        indexes = [
            models.Index(fields=["connected_account", "external_id"]),
            models.Index(fields=["customer", "channel"]),
            # Drives the daily "which identities need re-syncing?" query.
            models.Index(fields=["store", "last_synced_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.display_name or self.external_id} @ {self.channel.slug}"


class CustomerNote(TenantBaseModel):
    """An internal note attached to a customer (timeline entry)."""

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="customer_notes",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="customer_notes",
    )
    body = models.TextField()

    class Meta:
        ordering = ["-created_at"]
        db_table = "messaging_customer_note"
        indexes = [
            models.Index(fields=["customer", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Note on {self.customer_id}"


# ---------------------------------------------------------------------------
# Conversation layer
# ---------------------------------------------------------------------------
class Conversation(TenantBaseModel):
    """A threaded conversation between a customer and the store.

    One (active) conversation per (connected_account, customer): a
    partial unique constraint keeps a single OPEN/PENDING thread; once
    resolved/closed a new one can be opened. Denormalized fields
    (``last_message_at``, ``last_message_preview``, ``unread_count``,
    ``message_count``) power an efficient inbox list without joining to
    the messages table on every render.
    """

    connected_account = models.ForeignKey(
        ConnectedAccount,
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    channel = models.ForeignKey(
        Channel,
        on_delete=models.PROTECT,
        related_name="conversations",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        related_name="conversations",
    )
    subject = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20,
        choices=ConversationStatus.choices,
        default=ConversationStatus.OPEN,
        db_index=True,
    )
    priority = models.CharField(
        max_length=20,
        choices=ConversationPriority.choices,
        default=ConversationPriority.NORMAL,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_conversations",
    )
    tags = models.ManyToManyField(CustomerTag, blank=True, related_name="conversations")

    # Denormalized for fast inbox listing.
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_message_preview = models.CharField(max_length=255, blank=True)
    last_message_direction = models.CharField(
        max_length=10, choices=MessageDirection.choices, blank=True
    )
    unread_count = models.PositiveIntegerField(default=0)
    message_count = models.PositiveIntegerField(default=0)

    metadata = models.JSONField(default=dict, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="closed_conversations",
    )

    class Meta:
        ordering = ["-last_message_at", "-created_at"]
        db_table = "messaging_conversation"
        constraints = [
            # Only one ACTIVE conversation per (account, customer). A
            # condition-based unique constraint lets resolved/closed
            # conversations coexist with a freshly opened one.
            models.UniqueConstraint(
                fields=["connected_account", "customer"],
                condition=models.Q(status__in=ACTIVE_CONVERSATION_STATUSES),
                name="uniq_active_conversation_per_account_customer",
            ),
        ]
        indexes = [
            models.Index(fields=["store", "status", "last_message_at"]),
            models.Index(fields=["store", "assigned_to", "status"]),
            models.Index(fields=["store", "channel", "status"]),
            models.Index(fields=["customer"]),
            models.Index(fields=["connected_account", "status"]),
        ]

    def __str__(self) -> str:
        return f"Conversation {self.pk} ({self.channel.slug})"

    @property
    def is_active(self) -> bool:
        return self.status in ACTIVE_CONVERSATION_STATUSES

    def mark_read(self) -> None:
        """Reset the unread counter (does not save by itself for callers
        that batch updates; the conversation service persists it)."""
        self.unread_count = 0


class Message(TenantBaseModel):
    """A single message in a conversation, regardless of channel.

    The ``(connected_account, external_id)`` pair is unique and is the
    webhook idempotency key: re-delivered platform events are skipped.
    ``raw_payload`` keeps the original platform JSON for debugging and
    re-processing, but services operate only on the normalized fields.
    """

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    connected_account = models.ForeignKey(
        ConnectedAccount,
        on_delete=models.CASCADE,
        related_name="messages",
    )
    channel = models.ForeignKey(
        Channel,
        on_delete=models.PROTECT,
        related_name="messages",
    )
    external_id = models.CharField(
        max_length=255,
        blank=True,
        db_index=True,
        help_text=_("Platform message id. Blank for outbound messages awaiting a platform id."),
    )
    direction = models.CharField(max_length=10, choices=MessageDirection.choices, db_index=True)
    sender_type = models.CharField(max_length=10, choices=SenderType.choices, db_index=True)
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_messages",
        help_text=_("The agent (User) who sent an outbound message, if any."),
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="messages",
        help_text=_("The customer on the other end (inbound sender or outbound recipient)."),
    )

    message_type = models.CharField(
        max_length=20, choices=MessageType.choices, default=MessageType.TEXT
    )
    text = models.TextField(blank=True)
    quick_replies = models.JSONField(
        default=list,
        blank=True,
        help_text=_("Ephemeral quick-reply options shown alongside the message."),
    )
    reply_to = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="replies",
    )

    # Delivery tracking. Inbound messages are typically already DELIVERED.
    delivery_status = models.CharField(
        max_length=20,
        choices=DeliveryStatus.choices,
        default=DeliveryStatus.PENDING,
        db_index=True,
    )
    external_timestamp = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_message = models.TextField(blank=True)

    raw_payload = models.JSONField(
        default=dict,
        blank=True,
        help_text=_("Original platform payload, kept for debugging / re-processing."),
    )
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        db_table = "messaging_message"
        constraints = [
            # Webhook idempotency: a platform message is only stored once.
            models.UniqueConstraint(
                fields=["connected_account", "external_id"],
                name="uniq_message_account_external_id",
                condition=~models.Q(external_id=""),
            ),
        ]
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["store", "created_at"]),
            models.Index(fields=["store", "sender_type"]),
            models.Index(fields=["delivery_status"]),
            models.Index(fields=["connected_account", "delivery_status"]),
        ]

    def __str__(self) -> str:
        return f"{self.direction} {self.message_type} ({self.pk})"


class Attachment(TenantBaseModel):
    """A media/file attachment on a message.

    ``external_url`` is the platform-hosted URL (often expiring);
    ``file`` is the locally cached copy, downloaded asynchronously by a
    Celery task so slow platforms don't block ingestion. Dimensional
    metadata (width/height/duration) is populated when known.
    """

    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    attachment_type = models.CharField(
        max_length=20, choices=AttachmentType.choices, default=AttachmentType.FILE
    )
    file = models.FileField(upload_to="messaging/attachments/%Y/%m/", blank=True, null=True)
    external_url = models.URLField(max_length=2048, blank=True)
    external_id = models.CharField(max_length=255, blank=True)
    mime_type = models.CharField(max_length=120, blank=True)
    file_name = models.CharField(max_length=255, blank=True)
    file_size = models.PositiveBigIntegerField(null=True, blank=True)
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    duration = models.PositiveIntegerField(
        null=True, blank=True, help_text=_("Seconds, for audio/video.")
    )
    thumbnail_url = models.URLField(max_length=2048, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["created_at"]
        db_table = "messaging_attachment"
        indexes = [
            models.Index(fields=["message"]),
            models.Index(fields=["attachment_type"]),
        ]

    def __str__(self) -> str:
        return f"{self.attachment_type} attachment ({self.pk})"


class InternalNote(TenantBaseModel):
    """A private, agent-to-agent note on a conversation (not sent to the customer)."""

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name="internal_notes",
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="internal_notes",
    )
    body = models.TextField()
    mentions = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="mentioned_in_notes",
    )

    class Meta:
        ordering = ["-created_at"]
        db_table = "messaging_internal_note"
        indexes = [
            models.Index(fields=["conversation", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"Note on conversation {self.conversation_id}"


# ---------------------------------------------------------------------------
# Supporting models
# ---------------------------------------------------------------------------
class Activity(TenantBaseModel):
    """An append-only record powering the unified customer timeline.

    Activities are emitted by the service layer on every meaningful
    event (message received/sent, conversation assigned, customer
    merged, ...). A customer OR a conversation may be referenced
    (both nullable) so the same stream feeds the customer timeline and
    the conversation audit view. Payload details go in ``metadata``.
    """

    customer = models.ForeignKey(
        Customer,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="activities",
    )
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="activities",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="messaging_activities",
    )
    action_type = models.CharField(max_length=40, db_index=True)
    description = models.CharField(max_length=255, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "messaging_activity"
        indexes = [
            models.Index(fields=["customer", "created_at"]),
            models.Index(fields=["conversation", "created_at"]),
            models.Index(fields=["store", "action_type"]),
        ]

    def __str__(self) -> str:
        target = self.customer_id or self.conversation_id
        return f"{self.action_type} on {target}"


class MessageTemplate(TenantBaseModel):
    """A pre-approved reusable message template.

    WhatsApp requires pre-approved "HSM" templates for business-initiated
    messages; Messenger has reusable content. These are synced from the
    platform (``external_id``) but authored locally too, so a template
    can be drafted before submission for approval.
    """

    channel = models.ForeignKey(
        Channel,
        on_delete=models.PROTECT,
        related_name="templates",
    )
    connected_account = models.ForeignKey(
        ConnectedAccount,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="templates",
        help_text=_("Optional: scope a template to a specific connected account."),
    )
    name = models.CharField(max_length=120, db_index=True)
    language = models.CharField(max_length=10, default="en")
    category = models.CharField(max_length=80, blank=True)
    content = models.JSONField(
        default=dict,
        help_text=_("Template body: {header, body, footer, buttons, variables, ...}."),
    )
    variables = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=20,
        choices=MessageTemplateStatus.choices,
        default=MessageTemplateStatus.DRAFT,
        db_index=True,
    )
    external_id = models.CharField(max_length=255, blank=True, db_index=True)

    class Meta:
        ordering = ["name", "language"]
        db_table = "messaging_message_template"
        constraints = [
            models.UniqueConstraint(
                fields=["store", "channel", "name", "language"],
                name="uniq_template_store_channel_name_language",
            ),
        ]
        indexes = [
            models.Index(fields=["store", "status"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.language})"


class Reaction(TenantBaseModel):
    """A reaction (emoji) on a message — future-ready for platforms that support it."""

    message = models.ForeignKey(
        Message,
        on_delete=models.CASCADE,
        related_name="reactions",
    )
    reactor_type = models.CharField(
        max_length=10,
        choices=[("customer", "Customer"), ("agent", "Agent")],
        default="customer",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="message_reactions",
    )
    customer = models.ForeignKey(
        Customer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="message_reactions",
    )
    emoji = models.CharField(max_length=32)
    external_id = models.CharField(max_length=255, blank=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        db_table = "messaging_reaction"
        indexes = [
            models.Index(fields=["message"]),
        ]

    def __str__(self) -> str:
        return f"{self.emoji} on {self.message_id}"
