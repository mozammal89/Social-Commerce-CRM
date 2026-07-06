#!/usr/bin/env python
"""
Debug script to check subscription state
"""

import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from apps.permissions.models import Subscription, SubscriptionPlan
from apps.accounts.models import Tenant, User
from apps.stores.models import Store

print("\n" + "=" * 80)
print("SUBSCRIPTION DEBUG INFO")
print("=" * 80)

# Check all subscriptions
print("\n--- ALL SUBSCRIPTIONS ---")
subs = Subscription.objects.all()
for sub in subs:
    print(f"\nSubscription ID: {sub.id}")
    print(f"  Status: {sub.status}")
    print(f"  Plan: {sub.plan.name} ({sub.plan.slug})")
    print(f"  Plan ID: {sub.plan_id}")
    print(f"  Max Users: {sub.plan.max_users}")
    print(f"  Max Stores: {sub.plan.max_stores}")
    print(f"  Tenant ID: {sub.tenant_id}")
    print(f"  Store ID: {sub.store_id}")
    print(f"  Updated At: {sub.updated_at}")

# Check all plans
print("\n--- ALL PLANS ---")
plans = SubscriptionPlan.objects.all()
for plan in plans:
    print(f"\nPlan: {plan.name} ({plan.slug})")
    print(f"  Price: {plan.price}")
    print(f"  Max Users: {sub.plan.max_users if subs else 'N/A'}")
    print(f"  Max Stores: {sub.plan.max_stores if subs else 'N/A'}")

# Check tenants
print("\n--- ALL TENANTS ---")
tenants = Tenant.objects.all()
for tenant in tenants:
    print(f"\nTenant ID: {tenant.id}")
    print(f"  Name: {tenant.name}")
    print(f"  Owner: {tenant.owner.email if tenant.owner else 'N/A'}")
    print(
        f"  Has subscription: {hasattr(tenant, 'subscription') and tenant.subscription is not None}"
    )
    if hasattr(tenant, "subscription") and tenant.subscription:
        print(f"  Subscription Plan: {tenant.subscription.plan.name}")

# Check stores
print("\n--- ALL STORES ---")
stores = Store.objects.filter(is_deleted=False)
for store in stores:
    print(f"\nStore ID: {store.id}")
    print(f"  Name: {store.name}")
    print(f"  Tenant ID: {store.tenant_id}")
    print(
        f"  Has subscription: {hasattr(store, 'subscription') and store.subscription is not None}"
    )
    if hasattr(store, "subscription") and store.subscription:
        print(f"  Subscription Plan: {store.subscription.plan.name}")

print("\n" + "=" * 80)
