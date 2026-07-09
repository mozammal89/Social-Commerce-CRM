"""
DRF serializers for the omnichannel messaging API.

Split per use-case (matching the project convention in
``apps.stores.serializers``): read serializers are flat and denormalized
for the inbox, while write serializers only accept the fields the caller
may set. Serializers never mutate via the ORM directly — create/update
delegate to the service layer.
"""

from __future__ import annotations

from rest_framework import serializers

from apps.accounts.models import User
from apps.stores.models import Store

from . import services
from .models import (
    Activity,
    Attachment,
    Channel,
    ConnectedAccount,
    Conversation,
    Customer,
    CustomerChannelIdentity,
    CustomerNote,
    CustomerTag,
    InternalNote,
    Message,
)


# ===========================================================================
# Lightweight nested serializers (avoid full User serialization loops)
# ===========================================================================
class UserBriefSerializer(serializers.ModelSerializer):
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ["id", "email", "full_name", "avatar"]
        read_only_fields = fields

    def get_full_name(self, obj: User) -> str:
        return obj.get_full_name() or obj.email


class ChannelBriefSerializer(serializers.ModelSerializer):
    class Meta:
        model = Channel
        fields = ["id", "slug", "name", "channel_type", "icon"]
        read_only_fields = fields


# ===========================================================================
# Attachment
# ===========================================================================
class AttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Attachment
        fields = [
            "id", "attachment_type", "external_url", "external_id",
            "mime_type", "file_name", "file_size", "width", "height",
            "duration", "thumbnail_url",
        ]
        read_only_fields = fields


# ===========================================================================
# Message
# ===========================================================================
class MessageSerializer(serializers.ModelSerializer):
    """Full message read serializer (used in conversation detail)."""

    sender = UserBriefSerializer(read_only=True)
    attachments = AttachmentSerializer(many=True, read_only=True)
    channel = ChannelBriefSerializer(read_only=True)

    class Meta:
        model = Message
        fields = [
            "id", "conversation", "channel", "external_id", "direction",
            "sender_type", "sender", "message_type", "text", "quick_replies",
            "delivery_status", "external_timestamp", "sent_at", "delivered_at",
            "read_at", "failed_at", "error_code", "error_message",
            "attachments", "reply_to", "created_at",
        ]
        read_only_fields = fields


class SendMessageSerializer(serializers.Serializer):
    """Input for the send-reply endpoint (``POST .../messages/``).

    Delegates to ``MessageService.send``. Text is the common case;
    ``message_type`` lets the UI send image/document references later.
    """

    text = serializers.CharField(required=True, allow_blank=False, max_length=4000)
    message_type = serializers.CharField(required=False, default="text")
    reply_to = serializers.UUIDField(required=False)

    def validate_reply_to(self, value):
        # Belonging to the same conversation is enforced in the view via
        # the conversation's queryset; here we just confirm it exists.
        if not Message.objects.filter(id=value).exists():
            raise serializers.ValidationError("Unknown reply_to message.")
        return value


# ===========================================================================
# Conversation
# ===========================================================================
class ConversationListSerializer(serializers.ModelSerializer):
    """Denormalized, flat shape for fast inbox list rendering."""

    channel = ChannelBriefSerializer(read_only=True)
    customer_name = serializers.CharField(source="customer.display_name", read_only=True)
    customer_avatar = serializers.CharField(source="customer.avatar", read_only=True)
    customer_id = serializers.UUIDField(read_only=True)
    assigned_to = UserBriefSerializer(read_only=True)
    is_unread = serializers.SerializerMethodField()

    class Meta:
        model = Conversation
        fields = [
            "id", "channel", "customer_id", "customer_name", "customer_avatar",
            "subject", "status", "priority", "assigned_to", "unread_count",
            "message_count", "last_message_at", "last_message_preview",
            "last_message_direction", "is_unread", "created_at",
        ]
        read_only_fields = fields

    def get_is_unread(self, obj: Conversation) -> bool:
        return (obj.unread_count or 0) > 0


class ConversationDetailSerializer(serializers.ModelSerializer):
    """Rich conversation read for the detail pane."""

    channel = ChannelBriefSerializer(read_only=True)
    connected_account = serializers.StringRelatedField(read_only=True)
    customer = serializers.PrimaryKeyRelatedField(read_only=True)
    assigned_to = UserBriefSerializer(read_only=True)
    tags = serializers.SlugRelatedField(many=True, slug_field="name", read_only=True)

    class Meta:
        model = Conversation
        fields = [
            "id", "channel", "connected_account", "customer", "subject",
            "status", "priority", "assigned_to", "tags", "unread_count",
            "message_count", "last_message_at", "last_message_preview",
            "last_message_direction", "metadata", "closed_at", "created_at", "updated_at",
        ]
        read_only_fields = fields


class ConversationUpdateSerializer(serializers.ModelSerializer):
    """Partial update for status / priority / subject (assignment is a
    dedicated action endpoint)."""

    class Meta:
        model = Conversation
        fields = ["subject", "status", "priority"]


class AssignConversationSerializer(serializers.Serializer):
    """Input for the ``/assign/`` action. ``agent_id`` null = unassign."""

    agent_id = serializers.UUIDField(required=False, allow_null=True)


# ===========================================================================
# Internal note
# ===========================================================================
class InternalNoteSerializer(serializers.ModelSerializer):
    author = UserBriefSerializer(read_only=True)
    mentions = UserBriefSerializer(many=True, read_only=True)

    class Meta:
        model = InternalNote
        fields = ["id", "conversation", "author", "body", "mentions", "created_at", "updated_at"]
        read_only_fields = ["id", "conversation", "author", "mentions", "created_at", "updated_at"]


class InternalNoteCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = InternalNote
        fields = ["body"]


# ===========================================================================
# Customer
# ===========================================================================
class CustomerChannelIdentitySerializer(serializers.ModelSerializer):
    channel = ChannelBriefSerializer(read_only=True)

    class Meta:
        model = CustomerChannelIdentity
        fields = ["id", "channel", "connected_account", "external_id", "display_name", "avatar_url"]
        read_only_fields = fields


class CustomerSerializer(serializers.ModelSerializer):
    assigned_to = UserBriefSerializer(read_only=True)
    tags = serializers.SlugRelatedField(many=True, slug_field="name", read_only=True)
    channel_identities = CustomerChannelIdentitySerializer(many=True, read_only=True)
    open_conversations_count = serializers.SerializerMethodField()

    class Meta:
        model = Customer
        fields = [
            "id", "first_name", "last_name", "display_name", "email", "phone",
            "avatar", "assigned_to", "tags", "notes", "metadata",
            "channel_identities", "is_merged", "merged_into", "first_seen_at",
            "last_seen_at", "open_conversations_count", "created_at",
        ]
        read_only_fields = ["id", "avatar", "is_merged", "merged_into", "first_seen_at", "last_seen_at", "created_at"]

    def get_open_conversations_count(self, obj: Customer) -> int:
        # Cheap count; only computed on detail reads.
        return getattr(obj, "_open_conversations_count", None) or obj.conversations.filter(
            status__in=["open", "pending"]
        ).count()


class CustomerUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Customer
        fields = ["first_name", "last_name", "display_name", "email", "phone", "notes"]


class MergeCustomerSerializer(serializers.Serializer):
    """Input for the ``/customers/{id}/merge/`` action."""

    duplicate_id = serializers.UUIDField(required=True)

    def validate_duplicate_id(self, value):
        if not Customer.objects.filter(id=value).exists():
            raise serializers.ValidationError("Unknown customer.")
        return value


class CustomerTimelineSerializer(serializers.Serializer):
    """Read-only unified timeline (delegates to CustomerService.timeline)."""

    items = serializers.ListField(child=serializers.DictField(), read_only=True)

    def to_representation(self, instance: Customer):
        return {"items": services.CustomerService.timeline(instance)}


# ===========================================================================
# Connected channels
# ===========================================================================
class ConnectedAccountSerializer(serializers.ModelSerializer):
    """Read serializer. Credentials are NEVER serialized out."""

    channel = ChannelBriefSerializer(read_only=True)
    connected_by = UserBriefSerializer(read_only=True)
    is_active = serializers.BooleanField(read_only=True)

    class Meta:
        model = ConnectedAccount
        fields = [
            "id", "channel", "name", "external_id", "status", "is_active",
            "metadata", "connected_by", "last_synced_at", "error_message",
            "created_at", "updated_at",
        ]
        read_only_fields = fields


class ConnectChannelSerializer(serializers.Serializer):
    """Input for connecting a channel account (delegates to ChannelService).

    Credentials shape is channel-specific; the adapter validates it.
    """

    channel_slug = serializers.SlugRelatedField(
        slug_field="slug", queryset=Channel.objects.filter(is_enabled=True),
        source="channel",
    )
    external_id = serializers.CharField(required=True, max_length=255)
    name = serializers.CharField(required=True, max_length=200)
    credentials = serializers.DictField(required=True)
    webhook_verify_token = serializers.CharField(required=False, allow_blank=True, max_length=255)


class ConnectedAccountStatusSerializer(serializers.Serializer):
    """Input for the enable/disable action."""

    status = serializers.ChoiceField(choices=["connected", "disconnected"])


# ===========================================================================
# Activity (timeline entries — read only)
# ===========================================================================
class ActivitySerializer(serializers.ModelSerializer):
    actor = UserBriefSerializer(read_only=True)

    class Meta:
        model = Activity
        fields = ["id", "customer", "conversation", "actor", "action_type", "description", "metadata", "created_at"]
        read_only_fields = fields
