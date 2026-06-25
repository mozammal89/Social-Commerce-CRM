#!/usr/bin/env python
"""
Script to clear all subscription-related caches.

This can be used to force refresh of subscription data and seat counts
across all stores.
"""

import os
import sys
import django

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, "/home/md-monir/Development/Social-Commerce-CRM")
django.setup()

from django.core.cache import cache
from apps.subscriptions.constants import CACHE_SUBSCRIPTION_PREFIX, CACHE_PLAN_PREFIX


def clear_all_subscription_caches():
    """Clear all subscription and plan caches."""
    print("Clearing all subscription caches...")

    # Get all cache keys that match subscription patterns
    # Note: This depends on the cache backend used
    try:
        if hasattr(cache, "keys"):
            # Redis backend supports keys()
            subscription_keys = cache.keys(f"{CACHE_SUBSCRIPTION_PREFIX}*")
            plan_keys = cache.keys(f"{CACHE_PLAN_PREFIX}*")
            limit_keys = cache.keys("plan_limits_*")

            all_keys = subscription_keys + plan_keys + limit_keys

            if all_keys:
                print(f"Found {len(all_keys)} cache keys to clear:")
                for key in all_keys:
                    print(f"  - {key}")
                    cache.delete(key)

                print(f"✅ Cleared {len(all_keys)} cache keys")
            else:
                print("✅ No subscription caches found to clear")
        else:
            # For other cache backends, we can't easily list keys
            # So we'll just inform the user
            print("⚠️  Cache backend doesn't support key listing")
            print("💡 Consider restarting your application server to clear caches")

    except Exception as e:
        print(f"❌ Error clearing caches: {e}")
        import traceback

        traceback.print_exc()


def clear_store_subscription_cache(store_id):
    """Clear subscription cache for a specific store."""
    print(f"\nClearing cache for store {store_id}...")

    try:
        subscription_key = f"{CACHE_SUBSCRIPTION_PREFIX}{store_id}"
        plan_limit_key = f"plan_limits_{store_id}"

        deleted = []
        if cache.get(subscription_key):
            cache.delete(subscription_key)
            deleted.append(subscription_key)

        if cache.get(plan_limit_key):
            cache.delete(plan_limit_key)
            deleted.append(plan_limit_key)

        if deleted:
            print(f"✅ Cleared {len(deleted)} cache keys for store {store_id}")
        else:
            print(f"✅ No cached data found for store {store_id}")

    except Exception as e:
        print(f"❌ Error clearing cache for store {store_id}: {e}")


def list_all_stores():
    """List all stores for easy cache clearing."""
    from apps.stores.models import Store

    print(f"\n{'=' * 60}")
    print("ALL STORES")
    print(f"{'=' * 60}\n")

    stores = Store.objects.filter(is_deleted=False)
    print(f"Found {stores.count()} active stores:\n")

    for store in stores:
        print(f"ID: {store.id}, Name: {store.name}, Slug: {store.slug}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--all":
            clear_all_subscription_caches()
        else:
            try:
                store_id = sys.argv[1]
                clear_store_subscription_cache(store_id)
            except ValueError:
                print("Usage: python clear_caches.py [--all | <store_id>]")
                print("\nOptions:")
                print("  --all        Clear all subscription caches")
                print("  <store_id>   Clear cache for specific store")
                sys.exit(1)
    else:
        print("Usage: python clear_caches.py [--all | <store_id>]")
        print("\nOptions:")
        print("  --all        Clear all subscription caches")
        print("  <store_id>   Clear cache for specific store")
        print("\nListing all stores...")
        list_all_stores()
        print("\nExamples:")
        print("  python clear_caches.py --all")
        print("  python clear_caches.py 12345")
