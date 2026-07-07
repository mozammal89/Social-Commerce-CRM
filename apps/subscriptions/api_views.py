"""
API endpoint for getting aggregated subscription limits across all stores.
"""

from rest_framework.decorators import api_view, permission_classes
from rest_framework import permissions, status
from rest_framework.response import Response

from apps.stores.views import _resolve_max_stores_cap
from apps.stores.models import Store
from apps.permissions.services import active_memberships
from apps.accounts.models import User


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def get_aggregated_limits(request):
    """
    Get aggregated subscription limits across all stores the user has access to.

    This returns the highest tier plan limits from any subscription the user has access to,
    ensuring that if a user has upgraded to a higher-tier plan on any store, they get the benefits.
    """
    user = request.user

    # Get all stores the user has access to
    user_accessible_stores = Store.objects.filter(
        memberships__user=user, memberships__is_active=True, is_deleted=False
    ).distinct()

    current_store_count = user_accessible_stores.count()

    # Get the max stores cap using the fixed function
    max_stores = _resolve_max_stores_cap(user)

    # Calculate remaining stores
    remaining_stores = max(0, max_stores - current_store_count)

    # Resolve the live subscription once and reuse it for both name/slug
    # *and* the has-real-sub guard below. This keeps the plan name returned
    # in this response internally consistent with the limits (both come
    # from the same source of truth) and prevents stale ``pending_plan_slug``
    # markers from leaking through as the displayed plan name.
    from apps.subscriptions.services import resolve_user_subscription
    from apps.subscriptions.models import SubscriptionPlan

    live_subscription = resolve_user_subscription(user)
    has_real_subscription = (
        live_subscription is not None
        and getattr(live_subscription, "is_active", lambda: False)()
    )

    plan_name = "Unknown"
    plan_slug = "unknown"

    # Only honor ``pending_plan_slug`` when the user has *no* active
    # subscription yet — once a real sub exists, the marker is stale by
    # definition and would otherwise make plan_name disagree with the
    # live limits above.
    if not has_real_subscription and getattr(user, "pending_plan_slug", None):
        plan_slug = user.pending_plan_slug
        try:
            pending_plan = SubscriptionPlan.objects.get(slug=plan_slug)
            plan_name = pending_plan.name
        except SubscriptionPlan.DoesNotExist:
            plan_name = plan_slug.title()
    elif has_real_subscription and live_subscription is not None:
        # Resolve the plan from the highest-tier live subscription. Prefer
        # the live sub's plan object directly so plan_name/slug always
        # match the live subscription rather than a pending marker.
        from apps.subscriptions.models import Subscription

        accessible_store_ids = user_accessible_stores.values_list("id", flat=True)
        all_accessible_subs = (
            Subscription.objects.filter(
                store_id__in=accessible_store_ids, status__in=("active", "trialing")
            )
            .select_related("plan")
            .all()
        )

        if all_accessible_subs.exists():
            highest_plan = None
            highest_max_stores = 0

            for sub in all_accessible_subs:
                plan_max = getattr(sub.plan, "max_stores", 0)
                if plan_max > highest_max_stores:
                    highest_max_stores = plan_max
                    highest_plan = sub.plan

            if highest_plan:
                plan_name = highest_plan.name
                plan_slug = highest_plan.slug
        else:
            # No store-attached subs visible (could be tenant-only). Fall
            # back to the live sub's plan directly.
            plan_name = live_subscription.plan.name
            plan_slug = live_subscription.plan.slug

    return Response(
        {
            "limits": {
                "max_stores": max_stores,
                "current_stores": current_store_count,
                "remaining_stores": remaining_stores,
                "can_create_more": remaining_stores > 0,
            },
            "plan": {"name": plan_name, "slug": plan_slug},
        }
    )
