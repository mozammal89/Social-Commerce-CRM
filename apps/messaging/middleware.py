"""
WebSocket authentication middleware for Django Channels.

Browsers cannot set the ``Authorization`` header on WebSocket
connections, so the standard JWT header flow doesn't work over WS. Two
auth paths are supported here:

1. **JWT query param** — ``ws://.../ws/messaging/inbox/?token=<jwt>``.
   Resolved via SimpleJWT; the user is stashed on ``scope["user"]``.
2. **Session cookie fallback** — delegates to Channels'
   ``AuthMiddlewareStack`` for browser flows where the user is already
   logged in (session cookie present). This supports the HTMX/Alpine UI.

The middleware tries JWT first (query param), then session. If neither
resolves a user, ``scope["user"]`` is ``AnonymousUser`` and the
consumer's ``connect`` rejects the connection (fail-closed).
"""

from __future__ import annotations

import logging

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from channels.sessions import SessionMiddlewareStack
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.tokens import AccessToken, TokenError

logger = logging.getLogger(__name__)
User = get_user_model()

# Query-param key carrying the JWT for WebSocket connections.
TOKEN_QUERY_PARAM = "token"


@database_sync_to_async
def _get_user_from_token(token_string: str):
    """Resolve a user from a JWT access token string, or None."""
    try:
        token = AccessToken(token_string)
    except (TokenError, ValueError, TypeError):
        return None
    try:
        return User.objects.get(id=token["user_id"])
    except User.DoesNotExist:
        return None


class TokenAuthMiddleware(BaseMiddleware):
    """Resolve ``scope["user"]`` from a JWT query param or the session.

    Tries the JWT query param first; if absent or invalid, falls through
    to the session-based auth (so the same WS endpoint works for both
    the API client with a token and the browser with a session cookie).
    """

    async def __call__(self, scope, receive, send):
        # Only apply to websocket scopes.
        if scope.get("type") != "websocket":
            return await self.inner(scope, receive, send)

        # Parse the query string for a token. Channels gives it as bytes.
        query_string = scope.get("query_string", b"").decode()
        params = {}
        for pair in query_string.split("&"):
            if "=" in pair:
                k, _, v = pair.partition("=")
                params[k] = v

        token = params.get(TOKEN_QUERY_PARAM)
        user = None
        if token:
            user = await _get_user_from_token(token)

        if user is None or not user.is_authenticated:
            # Fall back to session-based auth for browser clients.
            # SessionMiddleware sets scope["user"] from the session cookie.
            session_user = scope.get("user", AnonymousUser())
            if getattr(session_user, "is_authenticated", False):
                user = session_user

        scope["user"] = user if (user and user.is_authenticated) else AnonymousUser()
        return await self.inner(scope, receive, send)


def TokenAuthMiddlewareStack(inner):
    """Compose session auth + token auth, like Channels' AuthMiddlewareStack.

    SessionMiddleware must wrap TokenAuthMiddleware so the session is
    available for the fallback path.
    """
    return SessionMiddlewareStack(TokenAuthMiddleware(inner))
