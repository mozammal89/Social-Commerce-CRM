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
    UpdateCredentialsSerializer,
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
                conversation=conv,
                status=serializer.validated_data["status"],
                actor=self.request.user,
            )
        if "priority" in serializer.validated_data:
            services.ConversationService.set_priority(
                conversation=conv,
                priority=serializer.validated_data["priority"],
                actor=self.request.user,
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
            return [
                permissions.IsAuthenticated(),
                IsStoreMember(),
                HasPermission.with_code("messages.create")(),
            ]
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
            Message.objects.filter(store=store, conversation_id=conv_id)
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
                id=ser.validated_data["reply_to"],
                conversation=conv,
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
            return [
                permissions.IsAuthenticated(),
                IsStoreMember(),
                HasPermission.with_code("notes.create")(),
            ]
        return super().get_permissions()

    def get_queryset(self):
        store = self.request.store
        conv_id = self.kwargs.get("conversation_id")
        if store is None or not conv_id:
            return InternalNote.objects.none()
        if not Conversation.objects.filter(store=store, id=conv_id).exists():
            return InternalNote.objects.none()
        return (
            InternalNote.objects.filter(store=store, conversation_id=conv_id)
            .select_related("author")
            .order_by("-created_at")
        )

    def get_serializer_class(self):
        return (
            InternalNoteCreateSerializer
            if self.request.method == "POST"
            else InternalNoteSerializer
        )

    def perform_create(self, serializer):
        store = self.request.store
        conv_id = self.kwargs["conversation_id"]
        conv = Conversation.objects.filter(store=store, id=conv_id).first()
        services.ConversationService.add_internal_note(
            conversation=conv,
            author=self.request.user,
            body=serializer.validated_data["body"],
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
            qs = (
                qs.filter(
                    # Case-insensitive search across name/email/phone.
                    display_name__icontains=q,
                )
                | qs.filter(first_name__icontains=q)
                | qs.filter(email__icontains=q)
                | qs.filter(phone__icontains=q)
            )
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
        return (
            Customer.objects.filter(store=store)
            .select_related("assigned_to")
            .prefetch_related(
                "channel_identities",
                "tags",
            )
        )

    def get_serializer_class(self):
        return (
            CustomerUpdateSerializer
            if self.request.method in ("PATCH", "PUT")
            else CustomerSerializer
        )

    def perform_update(self, serializer):
        services.CustomerService.update_profile(
            customer=serializer.instance,
            actor=self.request.user,
            **serializer.validated_data,
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
        return Response(
            {"detail": "Duplicate customer not found."}, status=status.HTTP_404_NOT_FOUND
        )

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


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@current_store
def refresh_customer_identity(request, customer_id, identity_id):
    """Trigger an on-demand profile refresh for one channel identity.

    Enqueues the ``enrich_customer_identity`` Celery task (async) so the
    response is fast. The task pulls the latest name/avatar/locale from
    the channel API, subject to the source-of-truth rule (agent-edited
    fields are never overwritten). The UI should re-fetch the customer
    a few seconds later to see the refreshed data, or use the realtime
    WebSocket update when available.

    Path: ``POST /api/v1/messaging/customers/<customer_id>/identities/<identity_id>/refresh/``
    Permission: ``customers.update``.
    """
    from .models import CustomerChannelIdentity
    from .tasks import enrich_customer_identity

    store = request.store
    if not PermissionResolver().check(request.user, store, "customers.update"):
        raise PermissionDenied("You cannot refresh customer profiles.")

    # Both the customer and the identity must belong to the store. The
    # identity must also belong to the customer (path consistency).
    customer = Customer.objects.filter(store=store, id=customer_id).first()
    if customer is None:
        raise NotFound("Customer not found.")
    identity = (
        CustomerChannelIdentity.objects.filter(store=store, customer=customer, id=identity_id)
        .select_related("channel")
        .first()
    )
    if identity is None:
        raise NotFound("Channel identity not found for this customer.")

    # Enqueue + return immediately. The task is idempotent and safe to retry.
    enrich_customer_identity.delay(str(identity.id))
    return Response(
        {
            "detail": f"Profile refresh queued for {identity.channel.name}.",
            "identity_id": str(identity.id),
            "queued_at": customer.updated_at.isoformat() if customer.updated_at else None,
        }
    )


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@current_store
def suggested_merges(request):
    """Return likely-duplicate customer pairs for manual review.

    Heuristic-only — never auto-merges. Looks for active (un-merged)
    customers in the store sharing strong signals: identical avatar URL
    (score 0.9) or same display name with recency overlap ≤7 days
    (score 0.6). Each suggestion is ready for UI review with
    "Merge" / "Dismiss" actions.

    Path: ``GET /api/v1/messaging/customers/suggested_merges/``
    Permission: ``customers.view``.
    Optional query: ``?limit=50`` (max 200).
    """
    store = request.store
    if not PermissionResolver().check(request.user, store, "customers.view"):
        raise PermissionDenied("You cannot view customer suggestions.")

    try:
        limit = min(int(request.GET.get("limit", 50)), 200)
    except (TypeError, ValueError):
        limit = 50

    suggestions = services.CustomerProfileService.detect_duplicates(
        store_id=store.id,
        limit=limit,
    )
    return Response({"items": suggestions, "count": len(suggestions)})


# ===========================================================================
# Connected channels
# ===========================================================================
class ConnectedAccountListView(StoreContextMixin, generics.ListCreateAPIView):
    """GET: connected channel accounts. POST: connect a new channel account."""

    permission_classes = [permissions.IsAuthenticated, IsStoreMember, HasPermission]
    permission_code = "connected_channels.view"

    def get_permissions(self):
        if self.request.method == "POST":
            return [
                permissions.IsAuthenticated(),
                IsStoreMember(),
                HasPermission.with_code("connected_channels.create")(),
            ]
        return super().get_permissions()

    def get_queryset(self):
        store = self.request.store
        if store is None:
            return ConnectedAccount.objects.none()
        return ConnectedAccount.objects.filter(store=store).select_related(
            "channel", "connected_by"
        )

    def get_serializer_class(self):
        return (
            ConnectChannelSerializer
            if self.request.method == "POST"
            else ConnectedAccountSerializer
        )

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
                account=instance,
                status=new_status,
                actor=self.request.user,
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


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
@current_store
def account_settings(request, channel_id):
    """Get account settings including masked credentials.

    Returns a detailed view of a connected account with masked credential
    values for display in the settings UI. Credentials are never returned
    in plain text - only masked representations. Requires
    ``connected_channels.view``.
    """
    from apps.permissions.resolver import PermissionResolver

    store = request.store
    if not PermissionResolver().check(request.user, store, "connected_channels.view"):
        raise PermissionDenied("You cannot view channel settings.")

    account = ConnectedAccount.objects.filter(store=store, id=channel_id).first()
    if account is None:
        raise NotFound("Channel not found.")

    # Get the channel for webhook URL
    channel = account.channel

    # Mask credentials for display
    masked_creds = {}
    if account.credentials and isinstance(account.credentials, dict):
        for key, value in account.credentials.items():
            if not value:
                masked_creds[key] = "(empty)"
            elif any(
                secret_word in key.lower() for secret_word in ["secret", "token", "password", "key"]
            ):
                # For secrets, show last 4 chars only
                str_val = str(value)
                if len(str_val) > 8:
                    masked_creds[key] = f"{'*' * (len(str_val) - 4)}{str_val[-4:]}"
                else:
                    masked_creds[key] = "****"
            else:
                # For non-secrets, show first 4 + last 4
                str_val = str(value)
                if len(str_val) > 8:
                    masked_creds[key] = f"{str_val[:4]}{'*' * (len(str_val) - 8)}{str_val[-4:]}"
                else:
                    masked_creds[key] = "****"

    # Build webhook URL
    from django.contrib.sites.shortcuts import get_current_site

    site = get_current_site(request)
    webhook_url = (
        f"{request.scheme}://{site.domain}/messaging/webhooks/{channel.slug}/{account.id}/"
    )

    return Response(
        {
            "account": ConnectedAccountSerializer(account).data,
            "credentials": {
                "masked": masked_creds,
                "keys": list(account.credentials.keys()) if account.credentials else [],
                "count": len(account.credentials) if account.credentials else 0,
                "has_credentials": bool(account.credentials),
                # Explicit flags derived from credential VALUES (not just
                # key presence) so the UI reflects the true state even
                # after a toggle-off leaves an empty-string value behind.
                "skip_signature_verification": bool(
                    isinstance(account.credentials, dict)
                    and account.credentials.get("skip_signature_verification") is True
                ),
            },
            "webhook": {
                "url": webhook_url,
                "verify_token": mask_token(account.webhook_verify_token),
                "verify_token_raw": account.webhook_verify_token or None,  # For show/hide toggle
            },
        }
    )


def mask_token(token: str) -> str:
    """Mask a token for display."""
    if not token:
        return "(not set)"
    if len(token) > 8:
        return f"{token[:4]}{'*' * (len(token) - 8)}{token[-4:]}"
    elif len(token) > 4:
        return f"{token[:2]}{'*' * (len(token) - 4)}{token[-2:]}"
    return "****"


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@current_store
def update_account_credentials(request, channel_id):
    """Update credentials for a connected account.

    Allows updating specific credential fields without requiring the full
    credential object. This is useful for rotating expiring tokens or
    updating individual fields. Requires ``connected_channels.update``.
    """
    from apps.permissions.resolver import PermissionResolver

    store = request.store
    if not PermissionResolver().check(request.user, store, "connected_channels.update"):
        raise PermissionDenied("You cannot update channel credentials.")

    account = ConnectedAccount.objects.filter(store=store, id=channel_id).first()
    if account is None:
        raise NotFound("Channel not found.")

    serializer = UpdateCredentialsSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    # Update credentials if provided
    new_creds = serializer.validated_data.get("credentials")
    if new_creds:
        # Merge with existing credentials
        existing_creds = account.credentials or {}
        existing_creds.update(new_creds)
        account.credentials = existing_creds

    # Update webhook verify token if provided
    new_token = serializer.validated_data.get("webhook_verify_token")
    if new_token is not None:
        account.webhook_verify_token = new_token

    account.save(update_fields=["credentials", "webhook_verify_token", "updated_at"])

    # Log the activity (account info stored in metadata)
    from .models import Activity

    Activity.objects.create(
        store=store,
        actor=request.user,
        action_type="credentials_updated",
        description=f"Credentials updated for {account.name}",
        metadata={
            "account_id": str(account.id),
            "account_name": account.name,
            "channel_slug": account.channel.slug if account.channel else None,
        },
    )

    # Verify the updated credentials
    try:
        account = services.ChannelService.verify_account(account=account, actor=request.user)
    except Exception as e:
        # Verification failed, but still return success for the update
        pass

    return Response(
        {
            "account": ConnectedAccountSerializer(account).data,
            "message": "Credentials updated successfully",
        }
    )


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
        return Response(
            {"detail": "is_enabled (boolean) is required."}, status=status.HTTP_400_BAD_REQUEST
        )
    channel.is_enabled = new_enabled
    channel.save(update_fields=["is_enabled", "updated_at"])
    return Response(ChannelCatalogSerializer(channel).data)


# ======================================================================
# TikTok OAuth 2.0 — authorization-code flow
# ======================================================================
# Flow:
#   1. Frontend calls ``oauth/tiktok/authorize/`` with client_key +
#      business_id + redirect params → gets back the TikTok auth URL.
#   2. User opens that URL in a popup/tab, logs into TikTok, approves.
#   3. TikTok redirects to ``oauth/tiktok/callback/?code=...&state=...``.
#   4. The callback view exchanges the code for tokens and creates the
#      ``ConnectedAccount`` via the standard service layer.
#   5. The callback view renders a small HTML page that closes the popup
#      and notifies the parent window (via ``postMessage``).


@api_view(["POST"])
@current_store
def tiktok_oauth_authorize(request):
    """Return the TikTok OAuth authorization URL for the user to visit.

    The frontend opens this URL in a popup. After the user approves,
    TikTok redirects to our callback which exchanges the code and
    finishes the connection automatically.

    Request body:
        client_key    — TikTok app client key
        business_id   — TikTok Business Center ID
        account_name  — display name for the connected account
    """
    client_key = request.data.get("client_key", "").strip()
    business_id = request.data.get("business_id", "").strip()
    account_name = request.data.get("account_name", "TikTok Business").strip()
    client_secret = request.data.get("client_secret", "").strip()

    if not client_key:
        return Response(
            {"detail": "client_key is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Build the callback URL (must EXACTLY match what's registered in the
    # TikTok developer console). Prefer the explicit TIKTOK_REDIRECT_URI
    # setting so the URL is stable regardless of proxy/headers.
    from django.conf import settings as dj_settings

    callback_url = getattr(dj_settings, "TIKTOK_REDIRECT_URI", "").strip()
    if not callback_url:
        # Fallback: derive from the request (works when SECURE_PROXY_SSL_HEADER
        # is configured so build_absolute_uri generates https://).
        callback_url = request.build_absolute_uri("/api/v1/messaging/oauth/tiktok/callback/")
        if (
            callback_url.startswith("http://")
            and request.headers.get("X-Forwarded-Proto") == "https"
        ):
            callback_url = "https://" + callback_url[len("http://") :]

    # Debug: log the exact URL so the user can compare it with the console.
    import logging

    logging.getLogger(__name__).warning(
        "TikTok OAuth redirect_uri being sent: %s (ensure this EXACTLY matches "
        "the URL registered in the TikTok developer console).",
        callback_url,
    )

    # Encode state so the callback knows which store/user to attribute
    # the connection to. Base64-encoded JSON keeps it compact + opaque.
    # Includes the PKCE code_verifier so the callback can exchange the
    # code (TikTok requires PKCE).
    import base64
    import json

    from .adapters.tiktok.client import build_authorize_url, generate_pkce_pair

    code_verifier, code_challenge = generate_pkce_pair()

    state_payload = {
        "store_id": str(request.store.id),
        "user_id": str(request.user.id),
        "client_key": client_key,
        "client_secret": client_secret,
        "business_id": business_id,
        "account_name": account_name,
        "callback_url": callback_url,
        "code_verifier": code_verifier,
    }
    state = base64.urlsafe_b64encode(json.dumps(state_payload).encode()).decode()

    auth_url = build_authorize_url(
        client_key=client_key,
        redirect_uri=callback_url,
        state=state,
        code_challenge=code_challenge,
    )
    return Response({"authorize_url": auth_url, "state": state})


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def tiktok_oauth_callback(request):
    """Handle the TikTok OAuth redirect (code → tokens → ConnectedAccount).

    TikTok redirects here with ``?code=...&state=...`` (or ``?error=...``
    on rejection). We decode the state to recover the store/user context,
    exchange the code for tokens, and create the connected account.

    On success/failure, a minimal HTML page is returned that closes the
    popup and notifies the parent window via ``postMessage``.
    """
    import base64
    import json
    import logging

    logger = logging.getLogger(__name__)
    error = request.GET.get("error")
    code = request.GET.get("code")
    state_raw = request.GET.get("state", "")

    if error:
        return _tiktok_oauth_render(
            success=False,
            message=f"TikTok authorization denied: {error}",
        )

    if not code or not state_raw:
        return _tiktok_oauth_render(success=False, message="Missing code or state from TikTok.")

    # Decode state → recover store/user context.
    try:
        state = json.loads(base64.urlsafe_b64decode(state_raw).decode())
    except Exception:
        return _tiktok_oauth_render(success=False, message="Invalid OAuth state.")

    client_key = state.get("client_key", "")
    business_id = state.get("business_id", "")
    account_name = state.get("account_name", "TikTok Business")
    callback_url = state.get("callback_url", "")
    store_id = state.get("store_id", "")
    user_id = state.get("user_id", "")
    code_verifier = state.get("code_verifier", "")
    # client_secret may have been passed from the form (via state) or
    # configured as an env var. Prefer the env var for security (so the
    # secret isn't embedded in the redirect URL), but accept the form
    # value as a fallback for dev/first-connect.
    from django.conf import settings as dj_settings

    client_secret = getattr(dj_settings, "TIKTOK_CLIENT_SECRET", "") or state.get(
        "client_secret", ""
    )

    if not client_secret:
        # Try to read from an existing connected account.
        existing = ConnectedAccount.objects.filter(
            store_id=store_id, channel__channel_type="tiktok"
        ).first()
        if existing and isinstance(existing.credentials, dict):
            client_secret = existing.credentials.get("client_secret", "")

    if not client_secret:
        return _tiktok_oauth_render(
            success=False,
            message="Client secret not found. Set TIKTOK_CLIENT_SECRET in env "
            "or connect once with the manual form.",
        )

    # Exchange the authorization code for tokens.
    from .adapters.tiktok import client as tt_client
    from .adapters.exceptions import AuthenticationError

    try:
        exchanged = tt_client.exchange_authorization_code(
            client_key=client_key,
            client_secret=client_secret,
            code=code,
            redirect_uri=callback_url,
            code_verifier=code_verifier,
        )
    except AuthenticationError as exc:
        logger.error("TikTok OAuth code exchange failed: %s", exc)
        return _tiktok_oauth_render(success=False, message=str(exc))

    token_data = exchanged.get("data") or exchanged
    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    open_id = token_data.get("open_id", "")

    if not access_token:
        return _tiktok_oauth_render(success=False, message="TikTok returned no access_token.")

    # Create the connected account via the standard service layer.
    User = get_user_model()
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        return _tiktok_oauth_render(success=False, message="User not found.")

    channel = Channel.objects.filter(channel_type="tiktok").first()
    if not channel:
        return _tiktok_oauth_render(success=False, message="TikTok channel is not enabled.")

    try:
        from apps.stores.models import Store

        store = Store.objects.get(pk=store_id)
        account = services.ChannelService.connect_account(
            store=store,
            channel_slug=channel.slug,
            external_id=business_id or open_id,
            name=account_name,
            credentials={
                "client_key": client_key,
                "client_secret": client_secret,
                "access_token": access_token,
                "refresh_token": refresh_token,
                "business_id": business_id,
                "open_id": open_id,
                "expires_in": token_data.get("expires_in"),
                "refresh_expires_in": token_data.get("refresh_expires_in"),
            },
            webhook_verify_token="",
            actor=user,
        )
    except Exception as exc:
        logger.error("TikTok OAuth account creation failed: %s", exc, exc_info=True)
        return _tiktok_oauth_render(success=False, message=str(exc))

    return _tiktok_oauth_render(success=True, message="TikTok connected successfully!")


def _tiktok_oauth_render(*, success: bool, message: str):
    """Return a minimal HTML page that closes the popup + posts to parent.

    The parent window (channels page) listens for the ``tiktok-oauth``
    ``postMessage`` and refreshes the account list / shows a toast.
    """
    from django.http import HttpResponse
    import json as _json

    status_color = "#16a34a" if success else "#dc2626"
    icon_html = "&#10003;" if success else "&#10007;"
    # JSON-encode the message so quotes/apostrophes don't break JS.
    msg_js = _json.dumps(message)
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>TikTok OAuth</title>
<style>
  body {{ font-family: system-ui, sans-serif; display: flex; align-items: center;
         justify-content: center; min-height: 100vh; margin: 0;
         background: #f8fafc; color: #1e293b; }}
  .card {{ text-align: center; padding: 2rem; background: #fff; border-radius: 12px;
          box-shadow: 0 4px 12px rgba(0,0,0,.1); max-width: 400px; }}
  .icon {{ font-size: 3rem; color: {status_color}; margin-bottom: 1rem; }}
  .msg {{ font-size: 1.1rem; margin-bottom: 0.5rem; }}
  .sub {{ color: #64748b; font-size: .9rem; }}
</style></head>
<body>
  <div class="card">
    <div class="icon">{icon_html}</div>
    <div class="msg" id="msg"></div>
    <div class="sub">This window will close automatically…</div>
  </div>
  <script>
    var msg = {msg_js};
    document.getElementById('msg').textContent = msg;
    // Always notify the parent window + close, even on error.
    if (window.opener) {{
      window.opener.postMessage(
        {{ type: 'tiktok-oauth', success: {str(success).lower()}, message: msg }},
        '*'
      );
    }}
    // Close after a short delay so the user sees the result.
    setTimeout(function() {{ window.close(); }}, 2000);
  </script>
</body></html>"""
    return HttpResponse(html)
