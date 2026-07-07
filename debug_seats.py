#!/usr/bin/env python
"""
Debug script to test seat counting logic.

This script helps identify why seat counting might be incorrect.
"""

import os
import sys
import django

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
sys.path.insert(0, "/home/md-monir/Development/Social-Commerce-CRM")
django.setup()

from apps.stores.models import Store
from apps.permissions.models import StoreMembership, Role
from apps.subscriptions.models import Subscription
from apps.accounts.models import User
from apps.subscriptions.services import check_plan_limits
from apps.settings.views import get_store_owners, calculate_seat_usage


def debug_store_seat_counting(store_id):
    """Debug seat counting for a specific store."""
    print(f"\n{'=' * 60}")
    print(f"DEBUGGING STORE ID: {store_id}")
    print(f"{'=' * 60}\n")

    try:
        store = Store.objects.get(id=store_id)
    except Store.DoesNotExist:
        print(f"❌ Store {store_id} not found")
        return

    print(f"Store: {store.name} (ID: {store.id})")
    print(f"Slug: {store.slug}")
    print(f"Deleted: {store.is_deleted}")
    print()

    # Get all memberships
    all_memberships = StoreMembership.objects.filter(store=store)
    print(f"Total memberships (active + inactive): {all_memberships.count()}")

    active_memberships = all_memberships.filter(is_active=True)
    print(f"Active memberships: {active_memberships.count()}")
    print()

    # Get owner role
    try:
        owner_role = Role.objects.get(slug="store-owner", store__isnull=True)
        print(f"✅ Found owner role: {owner_role.name} (ID: {owner_role.id})")
    except Role.DoesNotExist:
        print(f"❌ Owner role not found!")
        return

    # Get owner memberships
    owner_memberships = active_memberships.filter(role=owner_role)
    print(f"\nOwner memberships: {owner_memberships.count()}")
    for membership in owner_memberships:
        print(
            f"  - User ID: {membership.user_id}, Email: {membership.user.email}, Active: {membership.is_active}"
        )

    # Get owner IDs
    owner_ids = list(owner_memberships.values_list("user_id", flat=True))
    print(f"\nOwner IDs: {owner_ids}")

    # Count non-owner active memberships
    non_owner_memberships = active_memberships.exclude(user_id__in=owner_ids)
    print(f"\nNon-owner active memberships (should be seat count): {non_owner_memberships.count()}")
    for membership in non_owner_memberships:
        print(
            f"  - User ID: {membership.user_id}, Email: {membership.user.email}, Role: {membership.role.name}"
        )

    # Test get_store_owners function
    print(f"\n{'─' * 60}")
    print("Testing get_store_owners() function:")
    print(f"{'─' * 60}")
    owners = get_store_owners(store)
    print(f"Result: {owners}")
    print(f"Count: {len(owners)}")

    # Test calculate_seat_usage function
    print(f"\n{'─' * 60}")
    print("Testing calculate_seat_usage() function:")
    print(f"{'─' * 60}")
    seat_info = calculate_seat_usage(store)
    print(f"Used seats: {seat_info['used_seats']}")
    print(f"Total members: {seat_info['total_members']}")
    print(f"Owner count: {seat_info['owner_count']}")
    print(f"Owner IDs: {seat_info['owner_ids']}")

    # Test check_plan_limits function
    print(f"\n{'─' * 60}")
    print("Testing check_plan_limits() function:")
    print(f"{'─' * 60}")
    try:
        limits_info = check_plan_limits(store)
        print(f"Has active subscription: {limits_info.get('has_active_subscription', False)}")

        if limits_info.get("has_active_subscription"):
            plan = limits_info.get("plan", {})
            print(f"Plan: {plan.get('name', 'N/A')} (Slug: {plan.get('slug', 'N/A')})")

            limits = limits_info.get("limits", {})
            usage = limits_info.get("usage", {})

            print(f"\nLimits:")
            print(f"  Max users: {limits.get('max_users', 'N/A')}")
            print(f"  Max stores: {limits.get('max_stores', 'N/A')}")

            print(f"\nUsage:")
            print(f"  Users: {usage.get('users', 'N/A')}")
            print(f"  Stores: {usage.get('stores', 'N/A')}")

            exceeded = limits_info.get("exceeded", {})
            if exceeded:
                print(f"\n❌ EXCEEDED LIMITS:")
                for limit_type, info in exceeded.items():
                    print(f"  - {limit_type}: {info}")
            else:
                print(f"\n✅ All limits within bounds")
    except Exception as e:
        print(f"❌ Error checking plan limits: {e}")
        import traceback

        traceback.print_exc()

    print(f"\n{'=' * 60}")
    print("DEBUGGING COMPLETE")
    print(f"{'=' * 60}\n")


def list_all_stores():
    """List all stores for easy debugging."""
    print(f"\n{'=' * 60}")
    print("ALL STORES")
    print(f"{'=' * 60}\n")

    stores = Store.objects.filter(is_deleted=False)
    print(f"Found {stores.count()} active stores:\n")

    for store in stores:
        membership_count = StoreMembership.objects.filter(store=store, is_active=True).count()
        print(f"ID: {store.id}, Name: {store.name}, Members: {membership_count}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        store_id = sys.argv[1]
        try:
            debug_store_seat_counting(store_id)
        except Exception as e:
            print(f"Error: {e}")
            import traceback

            traceback.print_exc()
    else:
        print("Usage: python debug_seats.py <store_id>")
        print("\nListing all stores...")
        list_all_stores()
        print("\nRun with a store ID to debug that specific store.")
