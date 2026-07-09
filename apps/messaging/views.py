"""
Template views for the omnichannel messaging module.

Phase 1 ships the data layer (models + migrations). The unified inbox,
channels and customer views are built in later phases; until then these
views render a module-specific "coming soon" page so the sidebar links
resolve to something meaningful instead of a generic placeholder.

All views are ``@login_required`` (store context is resolved by the
dashboard layout / context processor). They deliberately do NOT enforce
RBAC here — the sidebar already gates visibility by permission, and a
dedicated permission check will be added together with the real views
in a later phase.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.shortcuts import render


# Context shared by every messaging coming-soon page. ``active_section``
# drives which sidebar item is highlighted and which card is emphasised.
_COMMON_CONTEXT = {
    "title": "Messaging",
    "active_section": "inbox",
}


@login_required
def inbox(request):
    """Unified Inbox landing page (coming soon)."""
    context = {
        **_COMMON_CONTEXT,
        "title": "Unified Inbox",
        "active_section": "inbox",
        "feature": {
            "name": "Unified Inbox",
            "icon": "bi-chat-dots",
            "blurb": "All your customer conversations — across every channel — in one place.",
            "capabilities": [
                "Facebook Messenger, WhatsApp & more in a single view",
                "Real-time incoming messages and live updates",
                "Assign conversations to teammates",
                "Internal notes, statuses and powerful search",
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
