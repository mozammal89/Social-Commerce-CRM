"""
Template views for the omnichannel messaging module.

The Unified Inbox (``inbox``) is a fully-built single-page view backed
by the REST API + WebSocket realtime layer. The Channels and Customers
pages still render a "coming soon" page until their dedicated UIs ship.

Store resolution for the inbox mirrors the dashboard: the session's
``current_store_id`` is honored if set; otherwise it falls back to the
first store the user has an active membership in (and seeds the session
so subsequent requests don't re-resolve). This avoids the "Store context
required" 403 a user hits right after login, before they've switched
stores. RBAC (``conversations.view``) is enforced against the resolved
store via the resolver, which is store-aware.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.permissions.models import StoreMembership
from apps.permissions.resolver import PermissionResolver
from apps.stores.models import Store


# Context shared by every messaging coming-soon page. ``active_section``
# drives which sidebar item is highlighted and which card is emphasised.
_COMMON_CONTEXT = {
    "title": "Messaging",
    "active_section": "inbox",
}


def _resolve_store(request):
    """Resolve the current store for the inbox, with a first-store fallback.

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


@login_required
def inbox(request):
    """Unified Inbox — three-pane SPA (conversation list, thread, customer panel).

    The view itself renders only the shell + passes the resolved store id
    and current user id to the template (and thus to ``inbox.js``). All
    data loading, realtime updates and mutations happen client-side via
    the REST API and the WebSocket inbox consumer.
    """
    store = _resolve_store(request)

    # Store-aware RBAC: deny closed if there's no store or the user lacks
    # the permission. We check here (rather than via the @permission_required
    # decorator) because we resolve the store leniently first.
    if store is not None and not PermissionResolver().check(
        request.user, store, "conversations.view"
    ):
        from django.core.exceptions import PermissionDenied
        raise PermissionDenied("You do not have permission to view conversations.")

    context = {
        "title": "Unified Inbox",
        "active_section": "inbox",
        "store_id": str(store.id) if store else "",
        "current_user_id": str(request.user.id),
        "current_user_name": request.user.get_full_name() or request.user.email,
    }
    return render(request, "messaging/inbox.html", context)


@login_required
def channels(request):
    """Connected Channels management page (coming soon)."""
    context = {
        **_COMMON_CONTEXT,
        "title": "Channels",
        "active_section": "channels",
        "feature": {
            "name": "Connected Channels",
            "icon": "bi-broadcast",
            "blurb": "Connect Facebook Pages, WhatsApp Business numbers and more.",
            "capabilities": [
                "Connect multiple Facebook Pages per store",
                "Connect multiple WhatsApp Business Accounts",
                "Enable, disable and configure each channel",
                "Secure webhook handling for every platform",
            ],
        },
    }
    return render(request, "messaging/coming_soon.html", context)


@login_required
def customers(request):
    """Unified Customers page (coming soon)."""
    context = {
        **_COMMON_CONTEXT,
        "title": "Customers",
        "active_section": "customers",
        "feature": {
            "name": "Customers",
            "icon": "bi-person-rolodex",
            "blurb": "A unified profile for every customer across all their channels.",
            "capabilities": [
                "Merge profiles when a customer reaches out on multiple channels",
                "Unified timeline: messages, orders, notes and activities",
                "Tags, assignments and full conversation history",
                "360° customer context while you chat",
            ],
        },
    }
    return render(request, "messaging/coming_soon.html", context)



@login_required
def channels(request):
    """Connected Channels management page (coming soon)."""
    context = {
        **_COMMON_CONTEXT,
        "title": "Channels",
        "active_section": "channels",
        "feature": {
            "name": "Connected Channels",
            "icon": "bi-broadcast",
            "blurb": "Connect Facebook Pages, WhatsApp Business numbers and more.",
            "capabilities": [
                "Connect multiple Facebook Pages per store",
                "Connect multiple WhatsApp Business Accounts",
                "Enable, disable and configure each channel",
                "Secure webhook handling for every platform",
            ],
        },
    }
    return render(request, "messaging/coming_soon.html", context)


@login_required
def customers(request):
    """Unified Customers page (coming soon)."""
    context = {
        **_COMMON_CONTEXT,
        "title": "Customers",
        "active_section": "customers",
        "feature": {
            "name": "Customers",
            "icon": "bi-person-rolodex",
            "blurb": "A unified profile for every customer across all their channels.",
            "capabilities": [
                "Merge profiles when a customer reaches out on multiple channels",
                "Unified timeline: messages, orders, notes and activities",
                "Tags, assignments and full conversation history",
                "360° customer context while you chat",
            ],
        },
    }
    return render(request, "messaging/coming_soon.html", context)
