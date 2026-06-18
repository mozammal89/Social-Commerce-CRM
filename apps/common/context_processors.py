"""
Custom context processors for Social Commerce CRM.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.db import models
from apps.stores.models import Store

User = get_user_model()


def app_settings(request):
    """Add application settings to all templates."""
    return {
        "APP_NAME": "Social Commerce CRM",
        "APP_VERSION": "1.0.0",
        "DEBUG": settings.DEBUG,
    }


def current_store(request):
    """Add current store context if available.

    Bug 2 / Bug 15 fix: this used to query the legacy M2M (owners /
    managers / staff) and would return stores the user no longer has an
    active membership for. It now consults ``StoreMembership`` (active
    rows only), matching the resolution order used by the new
    ``@current_store`` decorator (session → first available).
    """
    context = {
        "current_store": None,
        "user_stores": [],
    }

    if not getattr(request.user, "is_authenticated", False):
        return context

    user = request.user

    # Bug 2: filter by active StoreMembership rows.
    context["user_stores"] = list(
        Store.objects.filter(
            memberships__user=user,
            memberships__is_active=True,
            is_deleted=False,
        ).distinct().order_by("name")
    )

    # Get current store from session or first available
    store_id = request.session.get("current_store_id")
    if store_id:
        for s in context["user_stores"]:
            if str(s.id) == str(store_id):
                context["current_store"] = s
                break

    # Set default store if none selected
    if not context["current_store"] and context["user_stores"]:
        context["current_store"] = context["user_stores"][0]

    return context