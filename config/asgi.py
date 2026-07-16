"""
ASGI config for Social Commerce CRM project.

Routes traffic to the Django HTTP app or to Channels WebSocket
consumers via a ``ProtocolTypeRouter``. This is the entry point
referenced by ``ASGI_APPLICATION`` in settings and served by Daphne
(the ASGI server that replaces ``runserver`` when ``daphne`` is listed
first in ``INSTALLED_APPS``).

WebSocket auth uses a custom middleware stack: JWT tokens are passed as
a ``token`` query parameter (browsers can't set Authorization headers on
WebSocket connections), so ``TokenAuthMiddleware`` resolves the user
before the consumer's ``connect`` runs.
"""

import os

from channels.routing import ProtocolTypeRouter, URLRouter
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

# Import the middleware after Django is configured so model lookups work.
from apps.messaging.routing import websocket_urlpatterns
from apps.messaging.middleware import TokenAuthMiddlewareStack  # noqa: E402

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter(
    {
        # Standard Django HTTP/ASGI requests.
        "http": django_asgi_app,
        # WebSocket chat / inbox realtime layer.
        "websocket": TokenAuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
    }
)
