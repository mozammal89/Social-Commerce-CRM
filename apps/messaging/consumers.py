"""
WebSocket consumers for the messaging realtime layer.

Two consumers:

* ``InboxConsumer`` — connects to ``ws://.../ws/messaging/inbox/`` and
  joins the ``inbox.<store_id>`` group. Receives new-message and
  conversation-update events for the whole store.

* ``ConversationConsumer`` — connects to
  ``ws://.../ws/messaging/conversations/<conv_id>/`` and joins the
  ``conversation.<conv_id>`` group. Receives per-conversation message
  and delivery-status events.

Auth is handled by ``TokenAuthMiddlewareStack`` (JWT query param or
session cookie) — by the time ``connect`` runs, ``scope["user"]`` is the
authenticated user or ``AnonymousUser``. Both consumers additionally
verify store membership and (for ConversationConsumer) that the
conversation belongs to the resolved store, so a user can never
subscribe to another store's realtime feed.

The service layer broadcasts events via
``channel_layer.group_send(group, {"type": "message.new", ...})``; the
matching handler methods (``message_new``, ``conversation_updated`` …)
serialize the payload and send it to the client as JSON.
"""

from __future__ import annotations

import json
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser

logger = logging.getLogger(__name__)


# ===========================================================================
# Shared helpers
# ===========================================================================
@database_sync_to_async
def _is_store_member(user, store_id: str) -> bool:
    """True if the user has an active membership in the store."""
    if getattr(user, "is_superuser", False):
        return True
    from apps.permissions.models import StoreMembership

    return StoreMembership.objects.filter(
        user=user, store_id=store_id, is_active=True,
    ).exists()


@database_sync_to_async
def _conversation_store_id(conversation_id: str) -> str | None:
    """Return the store id that owns a conversation, or None if missing."""
    from .models import Conversation

    conv = Conversation.objects.filter(id=conversation_id).values_list("store_id", flat=True).first()
    return str(conv) if conv else None


# ===========================================================================
# Inbox consumer — store-wide conversation feed
# ===========================================================================
class InboxConsumer(AsyncJsonWebsocketConsumer):
    """Subscribes to all conversation updates for a store."""

    async def connect(self):
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            await self.close(code=4401)  # unauthorized
            return

        # The store id is passed as a query param (?store=<uuid>) or read
        # from the session. We require it explicitly over WS so a user
        # can't listen to a store they're not a member of by relying on
        # a stale session value.
        store_id = self._query_param("store")
        if not store_id:
            await self.close(code=4400)
            return

        if not await _is_store_member(user, store_id):
            await self.close(code=4403)  # forbidden
            return

        self.store_id = store_id
        self.group_name = f"inbox.{store_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info("Inbox WS connected: user=%s store=%s", user.id, store_id)

    async def disconnect(self, code):
        group = getattr(self, "group_name", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    # ---- Broadcast handlers (called by group_send) -------------------
    # Each ``type`` in the group_send message maps to a method named
    # ``<type_with_underscores>``. We forward the payload to the client.

    async def message_new(self, event):
        """A new message arrived in any conversation in this store."""
        await self.send_json(event["payload"])

    async def message_updated(self, event):
        """A message's delivery status changed (sent/delivered/read/failed)."""
        await self.send_json(event["payload"])

    async def conversation_updated(self, event):
        """A conversation's metadata changed (status, assignment, preview)."""
        await self.send_json(event["payload"])

    async def conversation_assigned(self, event):
        """A conversation was assigned/unassigned."""
        await self.send_json(event["payload"])

    async def conversation_status_changed(self, event):
        """A conversation's status changed."""
        await self.send_json(event["payload"])

    # ---- Helpers -----------------------------------------------------
    def _query_param(self, key: str) -> str | None:
        qs = self.scope.get("query_string", b"").decode()
        for pair in qs.split("&"):
            if "=" in pair:
                k, _, v = pair.partition("=")
                if k == key:
                    return v
        return None


# ===========================================================================
# Conversation consumer — single-conversation message stream
# ===========================================================================
class ConversationConsumer(AsyncJsonWebsocketConsumer):
    """Subscribes to one conversation's message + delivery events."""

    async def connect(self):
        user = self.scope.get("user")
        if not user or isinstance(user, AnonymousUser) or not user.is_authenticated:
            await self.close(code=4401)
            return

        conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        store_id = await _conversation_store_id(conversation_id)
        if store_id is None:
            await self.close(code=4404)
            return

        if not await _is_store_member(user, store_id):
            await self.close(code=4403)
            return

        self.conversation_id = conversation_id
        self.group_name = f"conversation.{conversation_id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info("Conversation WS connected: user=%s conv=%s", user.id, conversation_id)

    async def disconnect(self, code):
        group = getattr(self, "group_name", None)
        if group:
            await self.channel_layer.group_discard(group, self.channel_name)

    # ---- Broadcast handlers -----------------------------------------

    async def message_new(self, event):
        await self.send_json(event["payload"])

    async def message_updated(self, event):
        """Delivery status change (sent/delivered/read/failed)."""
        await self.send_json(event["payload"])

    async def typing(self, event):
        """Typing indicator (future-ready)."""
        await self.send_json(event["payload"])
