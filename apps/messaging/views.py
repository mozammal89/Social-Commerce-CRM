"""
Template views for the omnichannel messaging module.

All three messaging pages — Inbox, Channels, Customers — are fully-built
single-page views backed by the DRF messaging API. Each renders only a
shell that passes the resolved store id (and current user id where
useful) to its Alpine component; all data loading and mutations happen
client-side over the REST API (and WebSockets for the inbox).

Store resolution mirrors the dashboard: the session's
``current_store_id`` is honored if set; otherwise it falls back to the
first store the user has an active membership in (and seeds the session
so subsequent requests + the API/WS pick up the same store). Each page
enforces its own store-aware permission via ``PermissionResolver``.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render

from apps.permissions.models import StoreMembership
from apps.permissions.resolver import PermissionResolver
from apps.stores.models import Store


def _resolve_store(request):
    """Resolve the current store, with a first-store fallback.

    Resolution order:
      1. ``session["current_store_id"]`` if it points to a store the user
         can access (active membership, or any store for superusers).
      2. Otherwise the first store the user can access.
      3. None if the user has no accessible stores.

    The resolved store is stashed on ``request.store`` and the session
    value is set when it was missing, so the REST API and the WebSocket
    consumer (which read the same session key) work consistently.
    """
    user = request.user
    qs = Store.objects.filter(is_deleted=False)
    if not getattr(user, "is_superuser", False):
        member_ids = StoreMembership.objects.filter(
            user=user, is_active=True,
        ).values_list("store_id", flat=True)
        qs = qs.filter(id__in=list(member_ids))
    qs = qs.order_by("name")

    store_id = request.session.get("current_store_id")
    store = qs.filter(id=store_id).first() if store_id else None
    if store is None:
        store = qs.first()
    if store is not None and not store_id:
        # Seed the session so the API/WS pick up the same store.
        request.session["current_store_id"] = str(store.id)
    request.store = store
    return store


def _require_store_permission(request, code: str) -> Store:
    """Resolve the store and enforce a store-aware permission code.

    Returns the resolved store. Raises ``PermissionDenied`` if there's no
    store or the user lacks ``code``. Used by all three messaging pages.
    """
    store = _resolve_store(request)
    if store is None or not PermissionResolver().check(request.user, store, code):
        raise PermissionDenied("You do not have permission to access this page.")
    return store


def _base_ctx(request, store: Store, title: str, section: str) -> dict:
    """Shared template context for the three messaging pages."""
    return {
        "title": title,
        "active_section": section,
        "store_id": str(store.id),
        "current_user_id": str(request.user.id),
        "current_user_name": request.user.get_full_name() or request.user.email,
        "current_user_email": request.user.email,
    }


@login_required
def inbox(request):
    """Unified Inbox — three-pane SPA."""
    store = _require_store_permission(request, "conversations.view")
    return render(request, "messaging/inbox.html", _base_ctx(request, store, "Unified Inbox", "inbox"))


@login_required
def channels(request):
    """Connected Channels — connect/enable/disable FB & WA accounts."""
    store = _require_store_permission(request, "connected_channels.view")
    return render(request, "messaging/channels.html", _base_ctx(request, store, "Channels", "channels"))


@login_required
def customers(request):
    """Unified Customers — list, search, timeline, merge."""
    store = _require_store_permission(request, "customers.view")
    return render(request, "messaging/customers.html", _base_ctx(request, store, "Customers", "customers"))



