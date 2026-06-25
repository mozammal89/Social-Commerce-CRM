"""
Django signals for subscription-related cache management.

These signals ensure that subscription and plan limit caches are cleared
when membership changes occur, keeping dashboard data accurate.
"""

from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.core.cache import cache

from apps.permissions.models import StoreMembership
from apps.subscriptions.constants import CACHE_SUBSCRIPTION_PREFIX


@receiver(post_save, sender=StoreMembership)
def clear_subscription_cache_on_membership_change(sender, instance, created, **kwargs):
    """
    Clear subscription cache when a membership is created or updated.

    This ensures that seat counts and plan limits are recalculated
    when memberships change.
    """
    if instance.store_id:
        cache_key = f"{CACHE_SUBSCRIPTION_PREFIX}{instance.store_id}"
        cache.delete(cache_key)

        # Also clear any plan-related cache for this store
        plan_cache_key = f"plan_limits_{instance.store_id}"
        cache.delete(plan_cache_key)


@receiver(post_delete, sender=StoreMembership)
def clear_subscription_cache_on_membership_delete(sender, instance, **kwargs):
    """
    Clear subscription cache when a membership is deleted.

    This ensures that seat counts are updated when members are removed.
    """
    if instance.store_id:
        cache_key = f"{CACHE_SUBSCRIPTION_PREFIX}{instance.store_id}"
        cache.delete(cache_key)

        # Also clear any plan-related cache for this store
        plan_cache_key = f"plan_limits_{instance.store_id}"
        cache.delete(plan_cache_key)
