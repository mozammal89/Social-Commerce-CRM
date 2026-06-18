"""
Context processor: expose a tiny RBAC facade to all templates.

Usage in templates::

    {{ rbac.user.email }}
    {{ rbac.has_feature:"marketing_campaigns" }}
    {{ rbac.current_store.name }}

This avoids the need to load the tag library just to access the user
or current store in a global template like ``base.html``.
"""

from __future__ import annotations


def rbac(request):
    """Inject ``rbac`` into template context."""
    user = getattr(request, "user", None)
    store = getattr(request, "store", None)
    return {
        "rbac": {
            "user": user,
            "store": store,
            "is_authenticated": bool(
                user is not None and getattr(user, "is_authenticated", False)
            ),
        }
    }
