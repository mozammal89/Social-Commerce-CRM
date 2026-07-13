"""
DRF API views for the omnichannel messaging system.

These are thin transport layers: they resolve ``request.store`` via
``StoreContextMixin`` (URL kwarg → header → session), enforce RBAC with
the existing ``HasPermission`` / ``IsStoreMember`` classes, and delegate
every mutation to the service layer (``apps.messaging.services``) — the
same convention as ``apps.stores.views`` and ``apps.permissions.ui.views``.

No routers are used (project convention): routes are declared in
``api_urls.py`` and mounted at ``/api/v1/messaging/``.

Store isolation is structural: every list/retrieve is scoped to
``request.store`` via ``StoreScopedQuerysetMixin`` (which denies-by-
default when no store is resolved), and writes flow through services
that re-anchor every row to the store.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db.models import Prefetch
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from apps.permissions.decorators import current_store
from apps.permissions.mixins import StoreContextMixin, StoreScopedQuerysetMixin
from apps.permissions.permissions import HasPermission, IsStoreMember
from apps.permissions.resolver import PermissionResolver

from . import services
from .models import (
    Channel,
    ConnectedAccount,
    Conversation,
    Customer,
    CustomerTag,
    InternalNote,
    Message,
)
from .serializers import (
    AssignConversationSerializer,
    ChannelCatalogSerializer,
    ConnectedAccountSerializer,
    ConnectChannelSerializer,
    ConversationDetailSerializer,
    ConversationListSerializer,
    ConversationUpdateSerializer,
    CustomerSerializer,
    CustomerTimelineSerializer,
    CustomerUpdateSerializer,
    InternalNoteCreateSerializer,
    InternalNoteSerializer,
    MergeCustomerSerializer,
    MessageSerializer,
    SendMessageSerializer,
)

User = get_user_model()


# ===========================================================================
# Unified Inbox — conversation list & detail
# ===========================================================================
class ConversationListView(StoreContextMixin, generics.ListCreateAPIView):
    """GET: inbox list with filters. POST: not used (conversations are
    created automatically on inbound messages)."""

    permission_classes = [permissions.IsAuthenticated, IsStoreMember, HasPermission]
    permission_code = "conversations.view"
    serializer_class = ConversationListSerializer

    def get_queryset(self):
        store = self.request.store
        if store is None:
            return Conversation.objects.none()
        qs = services.ConversationService.list_for_inbox(
            store=store,
            status=self.request.GET.get("status"),
            channel_id=self.request.GET.get("channel_id"),
            assigned_to=self.request.GET.get("assigned_to"),
            unassigned_only=self.request.GET.get("unassigned") == "true",
        )
        # Optional search query folds into the same queryset.
        q = self.request.GET.get("q")
        if q:
            qs = services.ConversationService.search(store=store, query=q)
        return qs


class ConversationDetailView(StoreContextMixin, generics.RetrieveUpdateAPIView):
    """GET: full conversation. PATCH: status / priority / subject."""

    permission_classes = [permissions.IsAuthenticated, IsStoreMember, HasPermission]
    permission_code = "conversations.view"
    object_permission_code = "conversations.update"
    serializer_class = ConversationDetailSerializer
    lookup_field = "id"

    def get_queryset(self):
        store = self.request.store
        if store is None:
            return Conversation.objects.none()
        return Conversation.objects.filter(store=store, is_deleted=False)

    def get_serializer_class(self):
        if self.request.method in ("PATCH", "PUT"):
            return ConversationUpdateSerializer
        return ConversationDetailSerializer

    def perform_update(self, serializer):
        conv = serializer.save()
        # Re-apply via the service so Activity rows are emitted consistently.
        # ``serializer.save()`` already wrote the fields; these calls
        # additionally record the audit Activity rows.
        if "status" in serializer.validated_data:
            services.ConversationService.set_status(
                conversation=conv, status=serializer.validated_data["status"], actor=self.request.user,
            )
        if "priority" in serializer.validated_data:
            services.ConversationService.set_priority(
                conversation=conv, priority=serializer.validated_data["priority"], actor=self.request.user,
            )


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@current_store
def assign_conversation(request, conversation_id):
    """Assign / unassign a conversation. ``agent_id`` null = unassign.

    ``@current_store`` resolves ``request.store`` from the header/session
    and enforces active membership. The fine-grained permission
    (``conversations.assign``) is checked here via the resolver.
    """
    store = request.store
    if not PermissionResolver().check(request.user, store, "conversations.assign"):
        raise PermissionDenied("You cannot assign conversations.")

    conv = Conversation.objects.filter(store=store, id=conversation_id).first()
    if conv is None:
        raise NotFound("Conversation not found.")

    ser = AssignConversationSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    agent_id = ser.validated_data.get("agent_id")
    agent = User.objects.filter(id=agent_id).first() if agent_id else None
    services.ConversationService.assign(conversation=conv, agent=agent, actor=request.user)
    return Response(ConversationDetailSerializer(conv).data)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@current_store
def mark_conversation_read(request, conversation_id):
    """Reset a conversation's unread counter (agent opened it)."""
    conv = Conversation.objects.filter(store=request.store, id=conversation_id).first()
    if conv is None:
        raise NotFound("Conversation not found.")
    services.ConversationService.mark_read(conversation=conv)
    return Response({"unread_count": conv.unread_count})


# ===========================================================================
# Messages — list + send reply
# ===========================================================================
class MessageListView(StoreContextMixin, generics.ListCreateAPIView):
    """GET: messages in a conversation (ascending). POST: send a reply."""

    permission_classes = [permissions.IsAuthenticated, IsStoreMember, HasPermission]
    # view-level: create permission (POST) — but read needs a different code.
    permission_code = "messages.view"

    def get_permissions(self):
        # Sending a reply requires messages.create; reading requires messages.view.
        # ``get_permissions`` must return INSTANCES; ``HasPermission.with_code``
        # returns a class, so we instantiate it.
        if self.request.method == "POST":
            return [permissions.IsAuthenticated(), IsStoreMember(), HasPermission.with_code("messages.create")()]
        return super().get_permissions()

    def get_queryset(self):
        store = self.request.store
        conv_id = self.kwargs.get("conversation_id")
        if store is None or not conv_id:
            return Message.objects.none()
        # Conversation must belong to the store (isolation guard).
        if not Conversation.objects.filter(store=store, id=conv_id).exists():
            return Message.objects.none()
        return (
            Message.objects
            .filter(store=store, conversation_id=conv_id)
            .select_related("sender")
            .prefetch_related("attachments")
            .order_by("created_at")
        )

    def get_serializer_class(self):
        return SendMessageSerializer if self.request.method == "POST" else MessageSerializer

    def create(self, request, *args, **kwargs):
        store = request.store
        conv_id = self.kwargs["conversation_id"]
        conv = Conversation.objects.filter(store=store, id=conv_id).first()
        if conv is None:
            return Response({"detail": "Conversation not found."}, status=status.HTTP_404_NOT_FOUND)

        ser = SendMessageSerializer(data=request.data)
        ser.is_valid(raise_exception=True)

        reply_to = None
        if ser.validated_data.get("reply_to"):
            reply_to = Message.objects.filter(
                id=ser.validated_data["reply_to"], conversation=conv,
            ).first()

        message = services.MessageService.send(
            conversation=conv,
            sender=request.user,
            text=ser.validated_data["text"],
            message_type=ser.validated_data.get("message_type", "text"),
            reply_to=reply_to,
        )
        return Response(MessageSerializer(message).data, status=status.HTTP_201_CREATED)


# ===========================================================================
# Internal notes
# ===========================================================================
class InternalNoteListView(StoreContextMixin, generics.ListCreateAPIView):
    """GET/POST internal notes for a conversation (private, never sent to customer)."""

    permission_classes = [permissions.IsAuthenticated, IsStoreMember, HasPermission]
    permission_code = "notes.view"

    def get_permissions(self):
        if self.request.method == "POST":
            return [permissions.IsAuthenticated(), IsStoreMember(), HasPermission.with_code("notes.create")()]
        return super().get_permissions()

    def get_queryset(self):
        store = self.request.store
        conv_id = self.kwargs.get("conversation_id")
        if store is None or not conv_id:
            return InternalNote.objects.none()
        if not Conversation.objects.filter(store=store, id=conv_id).exists():
            return InternalNote.objects.none()
        return (
            InternalNote.objects
            .filter(store=store, conversation_id=conv_id)
            .select_related("author")
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        return InternalNoteCreateSerializer if self.request.method == "POST" else InternalNoteSerializer

    def perform_create(self, serializer):
        store = self.request.store
        conv_id = self.kwargs["conversation_id"]
        conv = Conversation.objects.filter(store=store, id=conv_id).first()
        services.ConversationService.add_internal_note(
            conversation=conv, author=self.request.user, body=serializer.validated_data["body"],
        )


# ===========================================================================
# Customers
# ===========================================================================
class CustomerListView(StoreContextMixin, generics.ListAPIView):
    """GET: customers in the store (with optional search)."""

    permission_classes = [permissions.IsAuthenticated, IsStoreMember, HasPermission]
    permission_code = "customers.view"
    serializer_class = CustomerSerializer

    def get_queryset(self):
        store = self.request.store
        if store is None:
            return Customer.objects.none()
        qs = Customer.objects.filter(store=store, is_merged=False).select_related("assigned_to")
        q = self.request.GET.get("q")
        if q:
            qs = qs.filter(
                # Case-insensitive search across name/email/phone.
                display_name__icontains=q,
            ) | qs.filter(first_name__icontains=q) | qs.filter(email__icontains=q) | qs.filter(phone__icontains=q)
        return qs.distinct().order_by("-last_seen_at")


class CustomerDetailView(StoreContextMixin, generics.RetrieveUpdateAPIView):
    """GET/PATCH a customer profile."""

    permission_classes = [permissions.IsAuthenticated, IsStoreMember, HasPermission]
    permission_code = "customers.view"
    object_permission_code = "customers.update"
    lookup_field = "id"

    def get_queryset(self):
        store = self.request.store
        if store is None:
            return Customer.objects.none()
        return Customer.objects.filter(store=store).select_related("assigned_to").prefetch_related(
            "channel_identities", "tags",
        )

    def get_serializer_class(self):
        return CustomerUpdateSerializer if self.request.method in ("PATCH", "PUT") else CustomerSerializer

    def perform_update(self, serializer):
        services.CustomerService.update_profile(
            customer=serializer.instance, actor=self.request.user, **serializer.validated_data,
        )


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@current_store
def merge_customer(request, customer_id):
    """Merge a duplicate customer into the primary (path param)."""
    store = request.store
    if not PermissionResolver().check(request.user, store, "customers.update"):
        raise PermissionDenied("You cannot merge customers.")

    primary = Customer.objects.filter(store=store, id=customer_id).first()
    if primary is None:
        raise NotFound("Customer not found.")
    ser = MergeCustomerSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    duplicate = Customer.objects.filter(store=store, id=ser.validated_data["duplicate_id"]).first()
    if duplicate is None:
        return Response({"detail": "Duplicate customer not found."}, status=status.HTTP_404_NOT_FOUND)

    services.CustomerService.merge(primary=primary, duplicate=duplicate, actor=request.user)
    return Response(CustomerSerializer(primary).data)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@current_store
def customer_timeline(request, customer_id):
    """Unified timeline for a customer (messages + notes + activities)."""
    customer = Customer.objects.filter(store=request.store, id=customer_id).first()
    if customer is None:
        raise NotFound("Customer not found.")
    return Response(CustomerTimelineSerializer(customer).data)
    

# ===========================================================================
# Connected channels
# ===========================================================================
class ConnectedAccountListView(StoreContextMixin, generics.ListCreateAPIView):
    """GET: connected channel accounts. POST: connect a new channel account."""

    permission_classes = [permissions.IsAuthenticated, IsStoreMember, HasPermission]
    permission_code = "connected_channels.view"

    def get_permissions(self):
        if self.request.method == "POST":
            return [permissions.IsAuthenticated(), IsStoreMember(), HasPermission.with_code("connected_channels.create")()]
        return super().get_permissions()

    def get_queryset(self):
        store = self.request.store
        if store is None:
            return ConnectedAccount.objects.none()
        return ConnectedAccount.objects.filter(store=store).select_related("channel", "connected_by")

    def get_serializer_class(self):
        return ConnectChannelSerializer if self.request.method == "POST" else ConnectedAccountSerializer

    def create(self, request, *args, **kwargs):
        ser = ConnectChannelSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        account = services.ChannelService.connect_account(
            store=request.store,
            channel_slug=data["channel"].slug,
            external_id=data["external_id"],
            name=data["name"],
            credentials=data["credentials"],
            webhook_verify_token=data.get("webhook_verify_token", ""),
            actor=request.user,
        )
        return Response(ConnectedAccountSerializer(account).data, status=status.HTTP_201_CREATED)


class ConnectedAccountDetailView(StoreContextMixin, generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE a connected account. PATCH enables/disables via status."""

    permission_classes = [permissions.IsAuthenticated, IsStoreMember, HasPermission]
    permission_code = "connected_channels.view"
    object_permission_code = "connected_channels.update"
    serializer_class = ConnectedAccountSerializer
    lookup_field = "id"

    def get_queryset(self):
        store = self.request.store
        if store is None:
            return ConnectedAccount.objects.none()
        return ConnectedAccount.objects.filter(store=store)

    def perform_update(self, serializer):
        """Apply status changes via the service so Activity rows fire.

        The read serializer can't write, so we handle the only mutable
        field (``status``) explicitly via ``request.data`` (DRF has
        already parsed the body).
        """
        instance = serializer.instance
        new_status = self.request.data.get("status")
        allowed = {"connected", "disconnected"}
        if new_status in allowed:
            services.ChannelService.set_status(
                account=instance, status=new_status, actor=self.request.user,
            )
        instance.refresh_from_db()

    def perform_destroy(self, instance):
        # Soft-disable rather than hard-delete so history survives. A real
        # delete (dropping credentials) is an admin-only future action.
        services.ChannelService.disconnect(account=instance, actor=self.request.user)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@current_store
def verify_channel(request, channel_id):
    """Test a connected account's credentials against the platform.

    Calls the adapter's ``verify_credentials`` (a lightweight live GET)
    and returns the updated account with its new status (``connected`` /
    ``error``) and any error message. Used by the "Test connection"
    button in the channel card. Requires ``connected_channels.update``.
    """
    from apps.permissions.resolver import PermissionResolver
    store = request.store
    if not PermissionResolver().check(request.user, store, "connected_channels.update"):
        raise PermissionDenied("You cannot verify channels.")
    account = ConnectedAccount.objects.filter(store=store, id=channel_id).first()
    if account is None:
        raise NotFound("Channel not found.")
    account = services.ChannelService.verify_account(account=account, actor=request.user)
    return Response(ConnectedAccountSerializer(account).data)


# ===========================================================================
# Channel catalog — dynamic source for the connect UI + admin toggle
# ===========================================================================
class CatalogListView(StoreContextMixin, generics.ListAPIView):
    """List the channels a store can connect to.

    Returns the global catalog filtered to ``is_enabled=True`` channels
    (the super-admin's gate). Each row includes ``adapter_available`` so
    the UI can tell "enabled but adapter missing" from "ready to connect".
    Requires store membership (any role) — the catalog is the same for
    every store; per-store gating happens when an account is connected.
    """

    permission_classes = [permissions.IsAuthenticated, IsStoreMember]
    serializer_class = ChannelCatalogSerializer

    def get_queryset(self):
        return Channel.objects.filter(is_enabled=True).order_by("sort_order", "name")


class CatalogAdminListView(generics.ListAPIView):
    """Super-admin only: the FULL catalog (enabled + disabled).

    Used by the admin "manage channels" UI to toggle channels on/off
    platform-wide. Not store-scoped (the catalog is global).
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ChannelCatalogSerializer

    def get_queryset(self):
        if not self.request.user.is_superuser:
            return Channel.objects.none()
        return Channel.objects.order_by("sort_order", "name")


@api_view(["PATCH"])
@permission_classes([permissions.IsAuthenticated])
def toggle_channel(request, channel_id):
    """Super-admin only: enable/disable a channel platform-wide.

    Flips ``Channel.is_enabled``. This is the gate that controls whether
    the channel appears in any store's connect UI. Only superusers may
    call it — it's a deployment-wide setting, not a per-store one.
    """
    if not request.user.is_superuser:
        raise PermissionDenied("Only super-admins can toggle channels.")
    channel = Channel.objects.filter(id=channel_id).first()
    if channel is None:
        raise NotFound("Channel not found.")
    new_enabled = request.data.get("is_enabled")
    if not isinstance(new_enabled, bool):
        return Response({"detail": "is_enabled (boolean) is required."}, status=status.HTTP_400_BAD_REQUEST)
    channel.is_enabled = new_enabled
    channel.save(update_fields=["is_enabled", "updated_at"])
    return Response(ChannelCatalogSerializer(channel).data)
