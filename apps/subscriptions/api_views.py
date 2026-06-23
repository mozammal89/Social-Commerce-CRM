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

    # Find the highest tier plan name
    plan_name = "Unknown"
    plan_slug = "unknown"

    # Try to get plan info from user's pending plan or highest subscription
    if hasattr(user, "pending_plan_slug") and user.pending_plan_slug:
        plan_slug = user.pending_plan_slug
        try:
            from apps.permissions.models import SubscriptionPlan

            pending_plan = SubscriptionPlan.objects.get(slug=plan_slug)
            plan_name = pending_plan.name
        except Exception:
            plan_name = plan_slug.title()
    else:
        # Find the highest tier subscription
        from apps.permissions.models import Subscription

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
