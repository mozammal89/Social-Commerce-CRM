"""
Custom context processors for Social Commerce CRM.
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.db import models
from apps.stores.models import Store

User = get_user_model()


def _get_user_subscription_context(user):
    """
    Get subscription-related context for a user.

    Returns a dict with:
    - user_subscription: active subscription object or None
    - has_user_subscription: boolean
    - has_pending_subscription: boolean
    - pending_plan: plan object if pending or None
    """
    context = {
        "user_subscription": None,
        "has_user_subscription": False,
        "has_pending_subscription": False,
        "pending_plan": None,
    }

    if not user or not user.is_authenticated:
        return context

    # Check if user has existing subscriptions (regardless of pending plan)
    try:
        from apps.permissions.models import Subscription

        user_subscription = (
            Subscription.objects.filter(
                store__memberships__user=user,
                store__memberships__is_active=True,
                status__in=["trialing", "active"],
            )
            .select_related("plan")
            .first()
        )

        if user_subscription:
            context["user_subscription"] = user_subscription
            context["has_user_subscription"] = True
    except Exception:
        pass

    # Check for pending subscription (user subscribed but no store yet, or upgrading plan)
    if user.pending_plan_slug:
        context["has_pending_subscription"] = True
        try:
            from apps.permissions.models import SubscriptionPlan

            pending_plan = SubscriptionPlan.objects.get(slug=user.pending_plan_slug)
            context["pending_plan"] = pending_plan
        except SubscriptionPlan.DoesNotExist:
            pass

    return context


def app_settings(request):
    """Add application settings to all templates."""
    return {
        "APP_NAME": "Social Commerce CRM",
        "APP_VERSION": "1.0.0",
        "DEBUG": settings.DEBUG,
    }


def current_store(request):
    """Add current store and subscription context to all templates.

    Bug 2 / Bug 15 fix: this used to query the legacy M2M (owners /
    managers / staff) and would return stores the user no longer has an
    active membership for. It now consults ``StoreMembership`` (active
    rows only), matching the resolution order used by the new
    ``@current_store`` decorator (session → first available).

    Super Admin Fix: Superusers should see all stores regardless of
    membership, allowing them to switch between any store in the system.

    Subscription Context: Also provides subscription-related context
    globally so the sidebar can show "Create Store" menu consistently
    across all pages.
    """
    context = {
        "current_store": None,
        "user_stores": [],
    }

    if not getattr(request.user, "is_authenticated", False):
        return context

    user = request.user

    # Super Admin: Show all stores regardless of membership
    if user.is_superuser:
        context["user_stores"] = list(
            Store.objects.filter(
                is_deleted=False,
            ).order_by("name")
        )
    else:
        # Regular user: Only show stores with active membership
        context["user_stores"] = list(
            Store.objects.filter(
                memberships__user=user,
                memberships__is_active=True,
                is_deleted=False,
            )
            .distinct()
            .order_by("name")
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

    # Add subscription-related context
    context.update(_get_user_subscription_context(user))
    # Add user_has_no_store flag for templates
    context["user_has_no_store"] = len(context["user_stores"]) == 0

    return context
