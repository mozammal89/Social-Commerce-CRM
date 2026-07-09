"""
URL configuration for the omnichannel messaging app.

Template routes (inbox/channels/customers) and the public webhook
route live here. The webhook is mounted at ``/messaging/webhooks/``
under the app namespace so it inherits the same ``app_name``; it is
``csrf_exempt`` and verified by the adapter (signature / verify-token),
not by Django session auth.

Namespacing follows the project convention: ``app_name = "messaging"``
and routes are reversed as ``{% url 'messaging:inbox' %}`` etc.
"""

from django.urls import path

from . import views, webhooks

app_name = "messaging"

urlpatterns = [
    # Template views (UI)
    path("inbox/", views.inbox, name="inbox"),
    path("channels/", views.channels, name="channels"),
    path("customers/", views.customers, name="customers"),
    # Public webhook endpoint for all channels.
    #   /messaging/webhooks/<channel_slug>/<account_id>/
    path(
        "webhooks/<slug:channel_slug>/<uuid:account_id>/",
        webhooks.channel_webhook,
        name="webhook",
    ),
]
