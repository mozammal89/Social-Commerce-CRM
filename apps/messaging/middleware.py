"""
WebSocket authentication middleware for Django Channels.

Browsers cannot set the ``Authorization`` header on WebSocket
connections, so the standard JWT header flow doesn't work over WS. Two
auth paths are supported here:

1. **JWT query param** — ``ws://.../ws/messaging/inbox/?token=<jwt>``.
   Resolved via SimpleJWT; the user is stashed on ``scope["user"]``.
2. **Session cookie fallback** — for browser flows where the user is
   already logged in (session cookie present). This supports the
   HTMX/Alpine UI.

The middleware tries JWT first (query param), then session. If neither
resolves a user, ``scope["user"]`` is ``AnonymousUser`` and the
consumer's ``connect`` rejects the connection (fail-closed).
"""

from __future__ import annotations

import logging

from channels.auth import AuthMiddleware
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
    """Resolve ``scope["user"]`` from a JWT query param, or keep the
    session-resolved user set by the upstream ``AuthMiddleware``.

    Order in the stack is::

        SessionMiddleware -> AuthMiddleware -> TokenAuthMiddleware

    By the time this runs, ``AuthMiddleware`` has already read the
    session cookie (loaded by ``SessionMiddleware``) and populated
    ``scope["user"]`` with the logged-in user (or ``AnonymousUser``).
    This layer only overrides that if a valid JWT is supplied via the
    ``?token=`` query param; otherwise it leaves the session user in
    place. So both the browser (session cookie) and API clients (JWT
    query param) are authenticated.
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
        if token:
            # A JWT was supplied — prefer it over the session user.
            user = await _get_user_from_token(token)
            if user and user.is_authenticated:
                scope["user"] = user

        # If no/invalid token, leave scope["user"] as AuthMiddleware set it
        # (the session user, or AnonymousUser). The consumer rejects
        # AnonymousUser in connect().
        return await self.inner(scope, receive, send)


def TokenAuthMiddlewareStack(inner):
    """Compose session auth + Channels auth + token auth.

    Order matters: ``SessionMiddleware`` must be outermost so the session
    is loaded into ``scope["session"]``; ``AuthMiddleware`` then reads
    that session and populates ``scope["user"]`` with the logged-in user
    (this is the step that was missing — without it the session fallback
    always sees ``AnonymousUser``). ``TokenAuthMiddleware`` is innermost,
    overriding with a JWT if one is provided.
    """
    return SessionMiddlewareStack(AuthMiddleware(TokenAuthMiddleware(inner)))

