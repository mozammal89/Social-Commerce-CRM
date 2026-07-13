"""
API URL configuration for the omnichannel messaging app.

Mounted at ``/api/v1/messaging/`` in ``config.urls``. This is a separate
module from ``apps/messaging/urls.py`` (template + webhook routes) so
the JSON API and the public webhook live in distinct namespaces.

No DRF router (project convention): every route is an explicit ``path``.

Store context is resolved by ``StoreContextMixin`` on each view from the
``X-Store-Id`` header / session, so these routes are store-agnostic in
the URL itself.
"""

from django.urls import path

from . import api_views

app_name = "messaging_api"

urlpatterns = [
    # ---- Unified Inbox -------------------------------------------------
    path("conversations/", api_views.ConversationListView.as_view(), name="conversations"),
    path("conversations/<uuid:id>/", api_views.ConversationDetailView.as_view(), name="conversation-detail"),
    path("conversations/<uuid:conversation_id>/assign/", api_views.assign_conversation, name="conversation-assign"),
    path("conversations/<uuid:conversation_id>/read/", api_views.mark_conversation_read, name="conversation-read"),

    # ---- Messages ------------------------------------------------------
    path(
        "conversations/<uuid:conversation_id>/messages/",
        api_views.MessageListView.as_view(),
        name="conversation-messages",
    ),

    # ---- Internal notes ------------------------------------------------
    path(
        "conversations/<uuid:conversation_id>/notes/",
        api_views.InternalNoteListView.as_view(),
        name="conversation-notes",
    ),

    # ---- Customers -----------------------------------------------------
    path("customers/", api_views.CustomerListView.as_view(), name="customers"),
    path("customers/<uuid:id>/", api_views.CustomerDetailView.as_view(), name="customer-detail"),
    path("customers/<uuid:customer_id>/merge/", api_views.merge_customer, name="customer-merge"),
    path("customers/<uuid:customer_id>/timeline/", api_views.customer_timeline, name="customer-timeline"),

    # ---- Connected channels -------------------------------------------
    path("channels/", api_views.ConnectedAccountListView.as_view(), name="channels"),
    path("channels/<uuid:id>/", api_views.ConnectedAccountDetailView.as_view(), name="channel-detail"),
    path("channels/<uuid:channel_id>/verify/", api_views.verify_channel, name="channel-verify"),

    # ---- Channel catalog (dynamic connect UI source) ------------------
    path("catalog/", api_views.CatalogListView.as_view(), name="catalog"),
    path("admin/channels/", api_views.CatalogAdminListView.as_view(), name="admin-channels"),
    path("admin/channels/<uuid:channel_id>/toggle/", api_views.toggle_channel, name="admin-channel-toggle"),
]
