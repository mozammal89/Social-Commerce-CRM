"""
Shared pytest fixtures for ``apps.subscriptions.tests``.

Kept local to the subscriptions app so we don't depend on (and break)
the permissions app's conftest. Provides a small set of factories
for Tenant, Store, Plan, Subscription, and StoreMembership.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.utils import timezone


@pytest.fixture(autouse=True)
def _clear_cache():
    """Wipe the cache between tests so cache_version stamps start fresh."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user(db):
    """A plain authenticated user with no tenant / store yet."""
    from django.contrib.auth import get_user_model

    User = get_user_model()
    return User.objects.create_user(
        email="tester@example.com",
        password="x",
    )


@pytest.fixture
def tenant(db, user):
    """A Tenant owned by ``user`` with one store under it.

    We start with 1 store (Starter's ``max_stores``) so that
    ``downgrade_subscription`` to Starter passes the capacity check by
    default. ``extra_stores`` adds more on top to exercise the over-cap
    branch.
    """
    from apps.accounts.models import Tenant
    from apps.stores.models import Store

    t = Tenant.objects.create(name="Test Tenant", slug="test-tenant", owner=user, is_active=True)
    Store.objects.create(name="Store One", tenant=t, status="active", is_deleted=False)
    return t


@pytest.fixture
def extra_stores(db, tenant):
    """Add 4 more stores so the tenant has 5 total (above Starter's max_stores=1)."""
    from apps.stores.models import Store

    for i in range(2, 6):
        Store.objects.create(name=f"Store {i}", tenant=tenant, status="active", is_deleted=False)
    return tenant


@pytest.fixture
def owner_role(db):
    """The system 'store-owner' role, seeded on demand."""
    from apps.permissions.models import Role
    from apps.permissions.seeders.roles_seeder import RolesSeeder

    RolesSeeder().run()
    return Role.objects.get(slug="store-owner", store__isnull=True)


@pytest.fixture
def manager_role(db):
    """A non-owner role we can attach memberships to for counting."""
    from apps.permissions.models import Role
    from apps.permissions.seeders.roles_seeder import RolesSeeder

    RolesSeeder().run()
    return Role.objects.get(slug="manager", store__isnull=True)


@pytest.fixture
def extra_members(db, tenant, manager_role):
    """Add 5 manager-role memberships across the tenant's stores (above Starter's max_users=3)."""
    from django.contrib.auth import get_user_model
    from apps.permissions.models import StoreMembership

    User = get_user_model()
    stores = list(tenant.stores.all())
    for i in range(5):
        u = User.objects.create_user(
            email=f"member{i}@example.com",
            password="x",
        )
        StoreMembership.objects.create(
            user=u, store=stores[i % len(stores)], role=manager_role, is_active=True
        )
    return tenant


@pytest.fixture
def starter_plan(db):
    """The Starter plan from the seeder matrix (or a synthetic minimal one)."""
    from apps.subscriptions.models import SubscriptionPlan
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="test-starter",
        defaults={
            "name": "Test Starter",
            "price": 19,
            "currency": "USD",
            "billing_period": "monthly",
            "max_users": 3,
            "max_stores": 1,
            "max_products": 500,
            "max_orders_per_month": 1000,
            "max_warehouses": 1,
            "is_active": True,
            "is_public": True,
        },
    )
    return plan


@pytest.fixture
def growth_plan(db):
    """A higher-tier plan used as the *current* plan in downgrade tests."""
    from apps.subscriptions.models import SubscriptionPlan
    plan, _ = SubscriptionPlan.objects.get_or_create(
        slug="test-growth",
        defaults={
            "name": "Test Growth",
            "price": 49,
            "currency": "USD",
            "billing_period": "monthly",
            "max_users": 10,
            "max_stores": 3,
            "max_products": 5000,
            "max_orders_per_month": 10000,
            "max_warehouses": 3,
            "is_active": True,
            "is_public": True,
        },
    )
    return plan


@pytest.fixture
def tenant_with_growth_sub(db, tenant, growth_plan):
    """A tenant with an active Growth subscription."""
    from apps.subscriptions.models import Subscription

    return Subscription.objects.create(
        tenant=tenant,
        plan=growth_plan,
        status="active",
        starts_at=timezone.now(),
        current_period_end=timezone.now() + timezone.timedelta(days=30),
    )
