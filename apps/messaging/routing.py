"""
WebSocket URL routing for the messaging realtime layer.

Two endpoints, both JWT/session-authenticated via
``TokenAuthMiddlewareStack``:

* ``ws://host/ws/messaging/inbox/?token=<jwt>``
    Subscribes to all conversation updates for the user's current store.
    Receives ``message.new``, ``conversation.updated``, ``conversation.assigned``.

* ``ws://host/ws/messaging/conversations/<conv_id>/?token=<jwt>``
    Subscribes to a single conversation's message stream. Receives
    ``message.new``, ``message.updated`` (delivery status), ``typing``.

Group naming (used by the service-layer broadcast helpers):
* ``inbox.<store_id>``        — all conversations in a store
* ``conversation.<conv_id>``  — one conversation's messages
"""

from django.urls import re_path

from . import consumers

websocket_urlpatterns = [
    re_path(r"^ws/messaging/inbox/$", consumers.InboxConsumer.as_asgi()),
    re_path(
        r"^ws/messaging/conversations/(?P<conversation_id>[0-9a-fA-F-]{36})/$",
        consumers.ConversationConsumer.as_asgi(),
    ),
]
