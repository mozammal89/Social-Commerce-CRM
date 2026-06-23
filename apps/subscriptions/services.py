"""
Subscription services for managing subscription lifecycle and operations.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from django.db import transaction
from django.utils import timezone
from django.core.cache import cache

from .constants import (
    STATUS_TRIALING,
    STATUS_ACTIVE,
    STATUS_PAST_DUE,
    STATUS_CANCELED,
    STATUS_EXPIRED,
    EVENT_CREATED,
    EVENT_TRIAL_STARTED,
    EVENT_PAYMENT_SUCCEEDED,
    EVENT_PAYMENT_FAILED,
    EVENT_RENEWED,
    EVENT_UPGRADED,
    EVENT_DOWNGRADED,
    EVENT_CANCELED,
    EVENT_EXPIRED,
    EVENT_REACTIVATED,
    EVENT_PLAN_CHANGED,
    VALID_STATUS_TRANSITIONS,
    DEFAULT_TRIAL_DAYS,
    CACHE_SUBSCRIPTION_PREFIX,
    CACHE_PLAN_PREFIX,
    CACHE_KEY_TIMEOUT,
)
from .exceptions import (
    PlanLimitExceeded,
    SubscriptionInactiveError,
    PlanNotFoundError,
    SubscriptionAlreadyExistsError,
    TransitionNotAllowedError,
    TrialExpiredError,
)
from apps.permissions.models import (
    Subscription,
    SubscriptionPlan,
    SubscriptionEvent,
    StoreMembership,
)
from apps.stores.models import Store

logger = logging.getLogger(__name__)


def record_event(
    subscription: Subscription, event_type: str, *, actor=None, metadata: Dict[str, Any] = None
) -> SubscriptionEvent:
    """
    Record a subscription event with metadata.

    Args:
        subscription: The subscription instance
        event_type: The type of event being recorded
        actor: The user who triggered the event (if applicable)
        metadata: Additional event metadata

    Returns:
        The created SubscriptionEvent instance
    """
    return SubscriptionEvent.objects.create(
        subscription=subscription,
        event_type=event_type,
        occurred_at=timezone.now(),
        actor=actor,
        metadata=metadata or {},
    )


def validate_status_transition(current_status: str, new_status: str) -> bool:
    """
    Validate if a status transition is allowed.

    Args:
        current_status: Current subscription status
        new_status: Target status

    Returns:
        True if transition is valid, False otherwise
    """
    allowed_transitions = VALID_STATUS_TRANSITIONS.get(current_status, [])
    return new_status in allowed_transitions


def transition_status(
    subscription: Subscription,
    new_status: str,
    *,
    actor=None,
    reason: str = None,
    metadata: Dict[str, Any] = None,
) -> bool:
    """
    Move a subscription to a new status with event logging.

    Args:
        subscription: The subscription to transition
        new_status: The target status
        actor: The user triggering the transition
        reason: Reason for the transition
        metadata: Additional transition metadata

    Returns:
        True if status was changed, False if already at target status

    Raises:
        TransitionNotAllowedError: If transition is not valid
    """
    if subscription.status == new_status:
        return False

    if not validate_status_transition(subscription.status, new_status):
        raise TransitionNotAllowedError(subscription.status, new_status)

    old_status = subscription.status
    subscription.status = new_status

    # Map transitions to canonical event types
    transition = (old_status, new_status)
    event_type_map = {
        (STATUS_TRIALING, STATUS_ACTIVE): EVENT_PAYMENT_SUCCEEDED,
        (STATUS_TRIALING, STATUS_CANCELED): EVENT_CANCELED,
        (STATUS_TRIALING, STATUS_EXPIRED): EVENT_EXPIRED,
        (STATUS_ACTIVE, STATUS_PAST_DUE): EVENT_PAYMENT_FAILED,
        (STATUS_ACTIVE, STATUS_CANCELED): EVENT_CANCELED,
        (STATUS_ACTIVE, STATUS_EXPIRED): EVENT_EXPIRED,
        (STATUS_PAST_DUE, STATUS_ACTIVE): EVENT_RENEWED,
        (STATUS_PAST_DUE, STATUS_CANCELED): EVENT_CANCELED,
        (STATUS_PAST_DUE, STATUS_EXPIRED): EVENT_EXPIRED,
        (STATUS_CANCELED, STATUS_ACTIVE): EVENT_REACTIVATED,
    }

    event_type = event_type_map.get(transition, f"transition.{old_status}_to_{new_status}")

    payload = {"from": old_status, "to": new_status}
    if reason:
        payload["reason"] = reason
    if metadata:
        payload.update(metadata)

    subscription.save(update_fields=["status", "updated_at"])
    record_event(subscription, event_type, actor=actor, metadata=payload)

    # Clear subscription cache
    cache.delete(f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.store_id}")

    logger.info(f"Subscription {subscription.id} transitioned from {old_status} to {new_status}")
    return True


def create_trial_subscription(
    store: Store,
    plan: SubscriptionPlan,
    *,
    actor=None,
    trial_days: int = None,
    metadata: Dict[str, Any] = None,
) -> Subscription:
    """
    Create a new trial subscription for a store.

    Args:
        store: The store to create subscription for
        plan: The subscription plan to use
        actor: The user creating the subscription
        trial_days: Number of trial days (defaults from plan)
        metadata: Additional subscription metadata

    Returns:
        The created Subscription instance

    Raises:
        SubscriptionAlreadyExistsError: If store already has active subscription
    """
    if hasattr(store, "subscription") and store.subscription:
        if store.subscription.is_active():
            raise SubscriptionAlreadyExistsError(store.id)

    trial_duration = trial_days or plan.trial_days or DEFAULT_TRIAL_DAYS
    now = timezone.now()

    subscription = Subscription.objects.create(
        store=store,
        plan=plan,
        status=STATUS_TRIALING,
        starts_at=now,
        trial_ends_at=now + timedelta(days=trial_duration),
    )

    record_event(subscription, EVENT_TRIAL_STARTED, actor=actor, metadata=metadata or {})

    logger.info(f"Created trial subscription {subscription.id} for store {store.id}")
    return subscription


def create_paid_subscription(
    store: Store,
    plan: SubscriptionPlan,
    *,
    payment_gateway_id: str = None,
    customer_id: str = None,
    billing_period_start: datetime = None,
    billing_period_end: datetime = None,
    actor=None,
    metadata: Dict[str, Any] = None,
) -> Subscription:
    """
    Create a new paid subscription for a store.

    Args:
        store: The store to create subscription for
        plan: The subscription plan to use
        payment_gateway_id: Gateway subscription ID
        customer_id: Gateway customer ID
        billing_period_start: Start of billing period
        billing_period_end: End of billing period
        actor: The user creating the subscription
        metadata: Additional subscription metadata

    Returns:
        The created Subscription instance

    Raises:
        SubscriptionAlreadyExistsError: If store already has active subscription
    """
    if hasattr(store, "subscription") and store.subscription:
        if store.subscription.is_active():
            raise SubscriptionAlreadyExistsError(store.id)

    now = timezone.now()

    subscription = Subscription.objects.create(
        store=store,
        plan=plan,
        status=STATUS_ACTIVE,
        starts_at=now,
        current_period_start=billing_period_start or now,
        current_period_end=billing_period_end or (now + timedelta(days=30)),
        stripe_customer_id=customer_id,
        stripe_subscription_id=payment_gateway_id,
    )

    record_event(subscription, EVENT_CREATED, actor=actor, metadata=metadata or {})

    logger.info(f"Created paid subscription {subscription.id} for store {store.id}")
    return subscription


def cancel_subscription(
    subscription: Subscription,
    *,
    cancel_at_period_end: bool = False,
    actor=None,
    reason: str = None,
) -> Subscription:
    """
    Cancel an active subscription.

    Args:
        subscription: The subscription to cancel
        cancel_at_period_end: If True, cancel at period end; if False, cancel immediately
        actor: The user canceling the subscription
        reason: Reason for cancellation

    Returns:
        The updated Subscription instance
    """
    if cancel_at_period_end and subscription.status == STATUS_ACTIVE:
        subscription.ends_at = subscription.current_period_end
        subscription.save(update_fields=["ends_at", "updated_at"])

        record_event(
            subscription,
            EVENT_CANCELED,
            actor=actor,
            metadata={"reason": reason, "cancel_at_period_end": True},
        )

        logger.info(f"Scheduled cancellation for subscription {subscription.id} at period end")
    else:
        transition_status(subscription, STATUS_CANCELED, actor=actor, reason=reason)

    return subscription


def renew_subscription(
    subscription: Subscription,
    *,
    new_period_start: datetime = None,
    new_period_end: datetime = None,
    actor=None,
) -> Subscription:
    """
    Renew a subscription that's nearing expiration.

    Args:
        subscription: The subscription to renew
        new_period_start: Start of new billing period
        new_period_end: End of new billing period
        actor: The user renewing the subscription

    Returns:
        The updated Subscription instance
    """
    if subscription.status != STATUS_ACTIVE and subscription.status != STATUS_PAST_DUE:
        raise SubscriptionInactiveError(
            subscription.status, "Only active or past-due subscriptions can be renewed"
        )

    now = timezone.now()
    subscription.status = STATUS_ACTIVE
    subscription.current_period_start = new_period_start or now
    subscription.current_period_end = new_period_end or (now + timedelta(days=30))
    subscription.ends_at = None

    subscription.save(
        update_fields=[
            "status",
            "current_period_start",
            "current_period_end",
            "ends_at",
            "updated_at",
        ]
    )

    record_event(subscription, EVENT_RENEWED, actor=actor)

    logger.info(f"Renewed subscription {subscription.id}")
    return subscription


def upgrade_subscription(
    subscription: Subscription,
    new_plan: SubscriptionPlan,
    *,
    actor=None,
    proration_behavior: str = "create_prorations",
) -> Subscription:
    """
    Upgrade a subscription to a higher-tier plan.

    CRITICAL FIX: When a user upgrades their subscription, upgrade ALL stores
    they own to the new plan, not just the current store. This ensures
    consistent plan limits across all stores.

    Args:
        subscription: The subscription to upgrade
        new_plan: The new plan to upgrade to
        actor: The user upgrading the subscription
        proration_behavior: How to handle proration

    Returns:
        The updated Subscription instance
    """
    if new_plan.price <= subscription.plan.price:
        raise ValueError("New plan price must be higher for upgrades")

    old_plan = subscription.plan

    # Upgrade the specific subscription
    subscription.plan = new_plan
    subscription.save(update_fields=["plan", "updated_at"])

    # CRITICAL: Also upgrade all other subscriptions for stores owned by the same user
    try:
        from apps.permissions.models import StoreMembership, Subscription
        from apps.stores.models import Store
        from apps.accounts.models import User

        # Get all store owner memberships for the same user across all stores
        owner_memberships = (
            StoreMembership.objects.filter(
                user__subscriptions=subscription.store,  # Get the user from current subscription
                role__slug="store-owner",
                is_active=True,
            )
            .select_related("user", "store")
            .all()
        )

        # Get the user who owns the store
        store_owners = (
            StoreMembership.objects.filter(
                store=subscription.store, role__slug="store-owner", is_active=True
            )
            .select_related("user")
            .first()
        )

        if store_owners:
            user = store_owners.user

            # Find all stores where this user is the owner
            user_owned_stores = Store.objects.filter(
                memberships__user=user,
                memberships__role__slug="store-owner",
                memberships__is_active=True,
                is_deleted=False,
            ).distinct()

            # Upgrade subscriptions for all stores owned by this user
            for store in user_owned_stores:
                if store.id != subscription.store_id:  # Don't upgrade the current store again
                    try:
                        store_sub = Subscription.objects.get(store=store)
                        if (
                            store_sub.plan.max_stores < new_plan.max_stores
                        ):  # Only upgrade if current plan is lower
                            store_sub.plan = new_plan
                            store_sub.save(update_fields=["plan", "updated_at"])

                            # Record event for the upgraded store subscription
                            record_event(
                                store_sub,
                                EVENT_UPGRADED,
                                actor=actor,
                                metadata={
                                    "old_plan": store_sub.plan.slug,
                                    "new_plan": new_plan.slug,
                                    "bulk_upgrade": True,
                                    "original_store": subscription.store_id,
                                },
                            )

                            # Clear cache for this store
                            cache.delete(f"{CACHE_SUBSCRIPTION_PREFIX}{store_sub.store_id}")

                            # Bump store plan version
                            try:
                                from apps.permissions.cache import bump_store_plan_version

                                bump_store_plan_version(store_sub.store_id)
                            except Exception:
                                pass
                    except Subscription.DoesNotExist:
                        # Create subscription for stores that don't have one
                        try:
                            new_sub = Subscription.objects.create(
                                store=store,
                                plan=new_plan,
                                starts_at=timezone.now(),
                                status="trialing",
                                trial_ends_at=timezone.now() + timedelta(days=new_plan.trial_days)
                                if new_plan.trial_days
                                else None,
                            )
                            record_event(
                                new_sub,
                                EVENT_CREATED,
                                actor=actor,
                                metadata={
                                    "plan_slug": new_plan.slug,
                                    "bulk_upgrade": True,
                                },
                            )
                        except Exception as e:
                            logger.exception(
                                f"Failed to create subscription for store {store.id} during upgrade"
                            )

    except Exception as e:
        logger.exception(
            f"Failed to upgrade subscriptions for all stores owned by user during plan upgrade"
        )

    record_event(
        subscription,
        EVENT_UPGRADED,
        actor=actor,
        metadata={
            "old_plan": old_plan.slug,
            "new_plan": new_plan.slug,
            "proration_behavior": proration_behavior,
        },
    )

    # Clear plan cache
    cache.delete(f"{CACHE_PLAN_PREFIX}{old_plan.slug}")
    cache.delete(f"{CACHE_PLAN_PREFIX}{new_plan.slug}")
    cache.delete(f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.store_id}")

    # Clear user-specific cache for all store members to ensure they get new limits
    try:
        from apps.permissions.models import StoreMembership
        from apps.permissions.cache import invalidate_user_store_cache

        # Get all active members of the store
        memberships = StoreMembership.objects.filter(store=subscription.store, is_active=True)

        for membership in memberships:
            invalidate_user_store_cache(membership.user_id, subscription.store_id)
    except Exception:
        logger.exception("Failed to invalidate user cache on upgrade")

    # Bump the RBAC store-plan version so cached feature / permission sets
    # for this store are invalidated immediately on the next read.
    try:
        from apps.permissions.cache import bump_store_plan_version

        bump_store_plan_version(subscription.store_id)
    except Exception:
        logger.exception("Failed to bump store plan version on upgrade")

    logger.info(f"Upgraded subscription {subscription.id} from {old_plan.slug} to {new_plan.slug}")
    return subscription


def downgrade_subscription(
    subscription: Subscription,
    new_plan: SubscriptionPlan,
    *,
    actor=None,
    effective_at_period_end: bool = True,
) -> Subscription:
    """
    Downgrade a subscription to a lower-tier plan.

    Args:
        subscription: The subscription to downgrade
        new_plan: The new plan to downgrade to
        actor: The user downgrading the subscription
        effective_at_period_end: If True, change takes effect at period end

    Returns:
        The updated Subscription instance
    """
    if new_plan.price >= subscription.plan.price:
        raise ValueError("New plan price must be lower for downgrades")

    old_plan = subscription.plan

    if effective_at_period_end:
        # Schedule downgrade at period end
        subscription.metadata = subscription.metadata or {}
        subscription.metadata["pending_downgrade"] = new_plan.slug
        subscription.save(update_fields=["metadata", "updated_at"])

        record_event(
            subscription,
            EVENT_DOWNGRADED,
            actor=actor,
            metadata={
                "old_plan": old_plan.slug,
                "new_plan": new_plan.slug,
                "effective_at_period_end": True,
            },
        )

        logger.info(
            f"Scheduled downgrade for subscription {subscription.id} from {old_plan.slug} to {new_plan.slug}"
        )
    else:
        # Immediate downgrade
        subscription.plan = new_plan
        subscription.save(update_fields=["plan", "updated_at"])

        record_event(
            subscription,
            EVENT_DOWNGRADED,
            actor=actor,
            metadata={
                "old_plan": old_plan.slug,
                "new_plan": new_plan.slug,
                "effective_at_period_end": False,
            },
        )

        cache.delete(f"{CACHE_PLAN_PREFIX}{old_plan.slug}")
        cache.delete(f"{CACHE_PLAN_PREFIX}{new_plan.slug}")
        cache.delete(f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.store_id}")

        # Clear user-specific cache for all store members to ensure they get new limits
        try:
            from apps.permissions.models import StoreMembership
            from apps.permissions.cache import invalidate_user_store_cache

            # Get all active members of the store
            memberships = StoreMembership.objects.filter(store=subscription.store, is_active=True)

            for membership in memberships:
                invalidate_user_store_cache(membership.user_id, subscription.store_id)
        except Exception:
            logger.exception("Failed to invalidate user cache on downgrade")

        try:
            from apps.permissions.cache import bump_store_plan_version

            bump_store_plan_version(subscription.store_id)
        except Exception:
            logger.exception("Failed to bump store plan version on downgrade")

        logger.info(
            f"Downgraded subscription {subscription.id} from {old_plan.slug} to {new_plan.slug}"
        )

    return subscription


def get_active_subscription(store: Store) -> Optional[Subscription]:
    """
    Get the active subscription for a store with caching.

    Args:
        store: The store to get subscription for

    Returns:
        The active Subscription instance or None
    """
    cache_key = f"{CACHE_SUBSCRIPTION_PREFIX}{store.id}"
    subscription = cache.get(cache_key)

    if subscription is None:
        try:
            subscription = store.subscription
            if subscription and not subscription.is_active():
                subscription = None
        except Subscription.DoesNotExist:
            subscription = None

        if subscription:
            cache.set(cache_key, subscription, CACHE_KEY_TIMEOUT)

    return subscription


def check_plan_limits(store: Store) -> Dict[str, Any]:
    """
    Check current usage against plan limits for a store.

    Args:
        store: The store to check limits for

    Returns:
        Dict with limit information and usage
    """
    subscription = get_active_subscription(store)

    if not subscription:
        return {
            "has_active_subscription": False,
            "limits": {},
            "usage": {},
            "exceeded": {},
        }

    plan = subscription.plan

    # Get current usage
    stores_count = (
        Store.objects.filter(
            memberships__store=store,
            memberships__is_active=True,
            is_deleted=False,
        )
        .distinct()
        .count()
    )

    users_count = StoreMembership.objects.filter(
        store=store,
        is_active=True,
    ).count()

    limits = {
        "max_stores": plan.max_stores,
        "max_users": plan.max_users,
        "max_products": plan.max_products,
        "max_orders_per_month": plan.max_orders_per_month,
        "max_warehouses": plan.max_warehouses,
    }

    usage = {
        "stores": stores_count,
        "users": users_count,
        # Add more usage metrics as needed
        "products": 0,  # Implement when products module is ready
        "orders_this_month": 0,  # Implement when orders module is ready
        "warehouses": 0,  # Implement when warehouses module is ready
    }

    exceeded = {}
    for limit_type, limit_value in limits.items():
        usage_key = limit_type.replace("max_", "")
        current_value = usage.get(usage_key, 0)
        if current_value >= limit_value:
            exceeded[limit_type] = {
                "limit": limit_value,
                "current": current_value,
                "exceeded_by": current_value - limit_value,
            }

    return {
        "has_active_subscription": True,
        "plan": {
            "id": plan.id,
            "name": plan.name,
            "slug": plan.slug,
            "price": str(plan.price),
            "currency": plan.currency,
        },
        "limits": limits,
        "usage": usage,
        "exceeded": exceeded,
        "status": subscription.status,
        "is_active": subscription.is_active(),
    }


def enforce_plan_limit(store: Store, limit_type: str, current_value: int) -> None:
    """
    Enforce a plan limit for a store.

    Args:
        store: The store to enforce limit for
        limit_type: Type of limit (e.g., 'max_stores', 'max_users')
        current_value: Current usage value

    Raises:
        PlanLimitExceeded: If limit would be exceeded
    """
    subscription = get_active_subscription(store)

    if not subscription:
        raise PlanLimitExceeded(limit_type, current_value, 0)

    plan = subscription.plan
    limit_value = getattr(plan, limit_type, None)

    if limit_value is None:
        logger.warning(f"Plan limit {limit_type} not found for plan {plan.slug}")
        return

    if current_value >= limit_value:
        raise PlanLimitExceeded(limit_type, current_value, limit_value)


def check_trial_expiry(subscription: Subscription) -> bool:
    """
    Check if a trial subscription has expired and handle accordingly.

    Args:
        subscription: The trial subscription to check

    Returns:
        True if trial expired, False otherwise

    Raises:
        TrialExpiredError: If trial has expired
    """
    if subscription.status != STATUS_TRIALING:
        return False

    if subscription.trial_ends_at and subscription.trial_ends_at < timezone.now():
        transition_status(subscription, STATUS_EXPIRED, reason="trial_expired")
        raise TrialExpiredError(subscription.trial_ends_at)

    return False
