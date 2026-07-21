"""
Django admin configuration for the messaging system.

Registers all messaging models with appropriate list displays,
filters, search fields, and custom admin actions.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _
from django.db.models import Count, Q

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
    MessageTemplate,
    Reaction,
)
from .constants import (
    ConnectedAccountStatus,
    ConversationPriority,
    ConversationStatus,
    DeliveryStatus,
    MessageDirection,
    MessageType,
)


# ---------------------------------------------------------------------------
# Connection layer
# ---------------------------------------------------------------------------
@admin.register(Channel)
class ChannelAdmin(admin.ModelAdmin):
    """Admin interface for Channel model."""

    list_display = [
        "name",
        "slug",
        "channel_type",
        "is_enabled",
        "sort_order",
    ]
    list_filter = ["is_enabled", "channel_type"]
    search_fields = ["name", "slug", "description"]
    list_editable = ["is_enabled", "sort_order"]
    ordering = ["sort_order", "name"]

    fieldsets = (
        (_("Basic Information"), {
            "fields": ("name", "slug", "channel_type", "description")
        }),
        (_("Configuration"), {
            "fields": ("icon", "is_enabled", "sort_order", "adapter_class", "config_schema")
        }),
        (_("Capabilities"), {
            "fields": ("capabilities",),
            "classes": ("collapse",),
        }),
    )


@admin.register(ConnectedAccount)
class ConnectedAccountAdmin(admin.ModelAdmin):
    """Admin interface for ConnectedAccount model."""

    list_display = [
        "name",
        "channel",
        "external_id",
        "status",
        "store",
        "credentials_status",
        "is_active",
        "last_synced_at",
        "connected_by",
    ]
    list_filter = [
        "channel",
        "status",
        "store",
        "connected_by",
        "last_synced_at",
    ]
    search_fields = [
        "name",
        "external_id",
        "error_message",
    ]
    readonly_fields = ["created_at", "updated_at", "last_synced_at", "masked_credentials", "masked_webhook_token"]
    ordering = ["-created_at"]

    def is_active(self, obj):
        """Display active status with badge."""
        if obj.is_active:
            return format_html('<span class="badge bg-success">Active</span>')
        return format_html('<span class="badge bg-secondary">Inactive</span>')
    is_active.short_description = _("Status")
    is_active.admin_order_field = "status"

    def credentials_status(self, obj):
        """Show if credentials are present without revealing them."""
        if obj.credentials and isinstance(obj.credentials, dict) and obj.credentials:
            keys = list(obj.credentials.keys())
            return format_html(
                '<span class="badge bg-info" title="{}">✓ {} key(s)</span>',
                ", ".join(keys),
                len(keys)
            )
        return format_html('<span class="badge bg-secondary">No credentials</span>')
    credentials_status.short_description = _("Credentials")

    def masked_credentials(self, obj):
        """Display masked credentials in admin detail view."""
        if not obj.credentials or not isinstance(obj.credentials, dict):
            return "No credentials stored"

        masked_items = []
        for key, value in obj.credentials.items():
            if value:
                # Show first 4 chars and mask the rest for non-secret values
                # For secret values, show last 4 chars only
                if any(secret_word in key.lower() for secret_word in ['secret', 'token', 'password', 'key']):
                    # For secrets, show last 4 chars only
                    masked = f"{'*' * (len(str(value)) - 4)}{str(value)[-4:]}" if len(str(value)) > 8 else '****'
                else:
                    # For non-secrets, show more context
                    str_val = str(value)
                    if len(str_val) > 8:
                        masked = f"{str_val[:4]}{'*' * (len(str_val) - 8)}{str_val[-4:]}"
                    else:
                        masked = '****'
                masked_items.append(f"{key}: {masked}")
            else:
                masked_items.append(f"{key}: (empty)")

        return format_html('<pre style="background: #f5f5f5; padding: 10px; border-radius: 4px;">{}</pre>', "<br>".join(masked_items))
    masked_credentials.short_description = _("Credentials (Masked)")

    def masked_webhook_token(self, obj):
        """Display masked webhook verify token."""
        token = obj.webhook_verify_token
        if not token:
            return "Not set"
        if len(token) > 8:
            masked = f"{token[:4]}{'*' * (len(token) - 8)}{token[-4:]}"
        elif len(token) > 4:
            masked = f"{token[:2]}{'*' * (len(token) - 4)}{token[-2:]}"
        else:
            masked = '****'
        return format_html('<code style="background: #f5f5f5; padding: 4px 8px; border-radius: 3px;">{}</code>', masked)
    masked_webhook_token.short_description = _("Webhook Verify Token (Masked)")

    fieldsets = (
        (_("Account Information"), {
            "fields": ("store", "channel", "name", "external_id")
        }),
        (_("Status & Credentials"), {
            "fields": ("status", "masked_credentials", "masked_webhook_token", "metadata", "error_message")
        }),
        (_("Metadata"), {
            "fields": ("last_synced_at", "connected_by", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


# ---------------------------------------------------------------------------
# Customer layer
# ---------------------------------------------------------------------------
@admin.register(CustomerTag)
class CustomerTagAdmin(admin.ModelAdmin):
    """Admin interface for CustomerTag model."""

    list_display = ["name", "slug", "color", "store"]
    list_filter = ["store"]
    search_fields = ["name", "slug"]
    list_editable = ["color"]
    ordering = ["name"]

    fieldsets = (
        (_("Basic Information"), {
            "fields": ("store", "name", "slug", "color")
        }),
    )


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    """Admin interface for Customer model."""

    list_display = [
        "display_name",
        "email",
        "phone",
        "store",
        "assigned_to",
        "created_at",
    ]
    list_filter = [
        "store",
        "assigned_to",
        "created_at",
    ]
    search_fields = [
        "first_name",
        "last_name",
        "display_name",
        "email",
        "phone",
    ]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]

    fieldsets = (
        (_("Basic Information"), {
            "fields": ("store", "first_name", "last_name", "display_name", "avatar")
        }),
        (_("Contact Information"), {
            "fields": ("email", "phone")
        }),
        (_("Assignment"), {
            "fields": ("assigned_to",)
        }),
        (_("Metadata"), {
            "fields": ("merged_into", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


@admin.register(CustomerChannelIdentity)
class CustomerChannelIdentityAdmin(admin.ModelAdmin):
    """Admin interface for CustomerChannelIdentity model."""

    list_display = [
        "customer",
        "channel",
        "external_id",
        "display_name",
        "created_at",
    ]
    list_filter = [
        "channel",
        "created_at",
    ]
    search_fields = [
        "customer__display_name",
        "customer__email",
        "external_id",
        "display_name",
    ]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]

    fieldsets = (
        (_("Basic Information"), {
            "fields": ("customer", "connected_account", "channel", "external_id", "display_name")
        }),
        (_("Profile Data"), {
            "fields": ("avatar_url", "metadata")
        }),
        (_("Metadata"), {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


class CustomerNoteInline(admin.TabularInline):
    """Inline admin for CustomerNote."""

    model = CustomerNote
    extra = 0
    readonly_fields = ["created_at", "author"]
    can_delete = True


@admin.register(CustomerNote)
class CustomerNoteAdmin(admin.ModelAdmin):
    """Admin interface for CustomerNote model."""

    list_display = [
        "customer",
        "truncated_note",
        "author",
        "created_at",
    ]
    list_filter = [
        "store",
        "author",
        "created_at",
    ]
    search_fields = [
        "customer__display_name",
        "customer__email",
        "note",
    ]
    readonly_fields = ["created_at", "author"]
    ordering = ["-created_at"]

    def truncated_note(self, obj):
        """Return truncated version of note for list display."""
        return obj.note[:100] + "..." if len(obj.note) > 100 else obj.note
    truncated_note.short_description = _("Note")

    fieldsets = (
        (_("Basic Information"), {
            "fields": ("store", "customer", "note")
        }),
        (_("Metadata"), {
            "fields": ("created_at", "author"),
            "classes": ("collapse",),
        }),
    )


# ---------------------------------------------------------------------------
# Conversation layer
# ---------------------------------------------------------------------------
class InternalNoteInline(admin.TabularInline):
    """Inline admin for InternalNote."""

    model = InternalNote
    extra = 0
    readonly_fields = ["created_at", "author"]
    can_delete = True


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    """Admin interface for Conversation model."""

    inlines = [InternalNoteInline]

    list_display = [
        "id",
        "customer",
        "connected_account",
        "channel",
        "status",
        "priority",
        "assigned_to",
        "created_at",
    ]
    list_filter = [
        "store",
        "connected_account",
        "channel",
        "status",
        "priority",
        "assigned_to",
        "created_at",
    ]
    search_fields = [
        "customer__display_name",
        "customer__email",
        "id",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
        "last_message_at",
    ]
    ordering = ["-created_at"]

    fieldsets = (
        (_("Basic Information"), {
            "fields": ("store", "customer", "connected_account", "channel")
        }),
        (_("Status & Assignment"), {
            "fields": ("status", "priority", "assigned_to")
        }),
        (_("Metadata"), {
            "fields": ("last_message_at", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


class AttachmentInline(admin.TabularInline):
    """Inline admin for Attachment."""

    model = Attachment
    extra = 0
    readonly_fields = ["created_at"]
    can_delete = True


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    """Admin interface for Message model."""

    list_display = [
        "id",
        "conversation",
        "connected_account",
        "direction",
        "sender_type",
        "message_type",
        "delivery_status",
        "created_at",
    ]
    list_filter = [
        "store",
        "connected_account",
        "channel",
        "direction",
        "sender_type",
        "message_type",
        "delivery_status",
        "created_at",
    ]
    search_fields = [
        "id",
        "conversation__customer__display_name",
        "conversation__customer__email",
        "text",
        "external_id",
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
        "sent_at",
        "delivered_at",
        "read_at",
        "failed_at",
    ]
    ordering = ["-created_at"]

    inlines = [AttachmentInline]

    fieldsets = (
        (_("Basic Information"), {
            "fields": ("store", "conversation", "connected_account", "channel", "external_id")
        }),
        (_("Message Content"), {
            "fields": ("direction", "sender_type", "sender", "message_type", "text")
        }),
        (_("Status"), {
            "fields": ("delivery_status", "error_message")
        }),
        (_("Reply Context"), {
            "fields": ("reply_to",)
        }),
        (_("Timestamps"), {
            "fields": ("sent_at", "delivered_at", "read_at", "failed_at", "created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    """Admin interface for Attachment model."""

    list_display = [
        "message",
        "attachment_type",
        "file_name",
        "mime_type",
        "created_at",
    ]
    list_filter = [
        "attachment_type",
        "created_at",
    ]
    search_fields = [
        "message__id",
        "message__text",
        "file_name",
        "external_id",
    ]
    readonly_fields = ["created_at"]
    ordering = ["-created_at"]

    fieldsets = (
        (_("Basic Information"), {
            "fields": ("message", "attachment_type", "external_id")
        }),
        (_("File Information"), {
            "fields": ("file", "file_name", "mime_type", "file_size", "url")
        }),
        (_("Media Details"), {
            "fields": ("width", "height", "duration", "thumbnail_url")
        }),
        (_("Metadata"), {
            "fields": ("created_at",),
            "classes": ("collapse",),
        }),
    )


@admin.register(InternalNote)
class InternalNoteAdmin(admin.ModelAdmin):
    """Admin interface for InternalNote model."""

    list_display = [
        "conversation",
        "truncated_note",
        "author",
        "created_at",
    ]
    list_filter = [
        "store",
        "author",
        "created_at",
    ]
    search_fields = [
        "conversation__id",
        "note",
    ]
    readonly_fields = ["created_at", "author"]
    ordering = ["-created_at"]

    def truncated_note(self, obj):
        """Return truncated version of note for list display."""
        return obj.body[:100] + "..." if len(obj.body) > 100 else obj.body
    truncated_note.short_description = _("Note")

    fieldsets = (
        (_("Basic Information"), {
            "fields": ("store", "conversation", "body")
        }),
        (_("Metadata"), {
            "fields": ("created_at", "author"),
            "classes": ("collapse",),
        }),
    )


# ---------------------------------------------------------------------------
# Supporting models
# ---------------------------------------------------------------------------
@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    """Admin interface for Activity model."""

    list_display = [
        "id",
        "customer",
        "conversation",
        "action_type",
        "created_at",
    ]
    list_filter = [
        "store",
        "action_type",
        "created_at",
    ]
    search_fields = [
        "customer__display_name",
        "conversation__id",
        "id",
    ]
    readonly_fields = ["created_at"]
    ordering = ["-created_at"]

    fieldsets = (
        (_("Basic Information"), {
            "fields": ("store", "customer", "conversation", "action_type")
        }),
        (_("Activity Data"), {
            "fields": ("actor", "description", "metadata")
        }),
        (_("Metadata"), {
            "fields": ("created_at",),
            "classes": ("collapse",),
        }),
    )


@admin.register(MessageTemplate)
class MessageTemplateAdmin(admin.ModelAdmin):
    """Admin interface for MessageTemplate model."""

    list_display = [
        "name",
        "channel",
        "language",
        "status",
        "created_at",
    ]
    list_filter = [
        "store",
        "channel",
        "status",
        "language",
        "created_at",
    ]
    search_fields = [
        "name",
        "external_id",
        "content",
    ]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["-created_at"]

    fieldsets = (
        (_("Basic Information"), {
            "fields": ("store", "channel", "name", "external_id")
        }),
        (_("Template Content"), {
            "fields": ("content", "language", "status")
        }),
        (_("Metadata"), {
            "fields": ("created_at", "updated_at"),
            "classes": ("collapse",),
        }),
    )


@admin.register(Reaction)
class ReactionAdmin(admin.ModelAdmin):
    """Admin interface for Reaction model."""

    list_display = [
        "message",
        "emoji",
        "reactor_type",
        "created_at",
    ]
    list_filter = [
        "emoji",
        "reactor_type",
        "created_at",
    ]
    search_fields = [
        "message__id",
        "message__text",
        "emoji",
    ]
    readonly_fields = ["created_at"]
    ordering = ["-created_at"]

    fieldsets = (
        (_("Basic Information"), {
            "fields": ("store", "message", "emoji", "reactor_type")
        }),
        (_("Metadata"), {
            "fields": ("created_at",),
            "classes": ("collapse",),
        }),
    )
