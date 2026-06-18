"""
Shared pytest fixtures for the permissions app tests.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache

from apps.permissions.models import (
    Feature,
    Permission,
    PlanFeature,
    Resource,
    Role,
    RolePermission,
    StoreMembership,
    Subscription,
    SubscriptionPlan,
)
from apps.permissions.constants import (
    MODIFIER_GRANT,
    ROLE_STORE_OWNER,
    ROLE_VIEWER,
    ROLE_MANAGER,
    SUB_ACTIVE,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Wipe the cache between tests so cache_version stamps start fresh."""
    cache.clear()
    yield
    cache.clear()


def _make_store():
    """Create a minimal Store without relying on the buggy project factory."""
    from apps.stores.models import Store
    return Store.objects.create(name="Test Store", status="active")


@pytest.fixture
def resources(db):
    """Run the registry sync and return a dict of Resource objects by code."""
    from django.core.management import call_command
    call_command("sync_permissions", verbosity=0)
    return {r.code: r for r in Resource.objects.all()}


@pytest.fixture
def permissions(resources):
    """Return a dict of Permission objects by code."""
    return {p.code: p for p in Permission.objects.all()}


@pytest.fixture
def system_roles(db):
    """Seed system roles and return them as a dict by slug."""
    from apps.permissions.seeders.roles_seeder import RolesSeeder
    RolesSeeder().run()
    return {r.slug: r for r in Role.objects.filter(store=None)}


@pytest.fixture
def owner_role(system_roles):
    return system_roles[ROLE_STORE_OWNER]


@pytest.fixture
def manager_role(system_roles):
    return system_roles[ROLE_MANAGER]


@pytest.fixture
def viewer_role(system_roles):
    return system_roles[ROLE_VIEWER]


@pytest.fixture
def owner_membership(db, owner_role):
    """A user with the 'store-owner' role in a fresh store."""
    from tests.factories import UserFactory
    user = UserFactory()
    store = _make_store()
    membership = StoreMembership.objects.create(
        user=user, store=store, role=owner_role, is_active=True,
    )
    return user, store, membership


@pytest.fixture
def manager_membership(db, manager_role):
    from tests.factories import UserFactory
    user = UserFactory()
    store = _make_store()
    membership = StoreMembership.objects.create(
        user=user, store=store, role=manager_role, is_active=True,
    )
    return user, store, membership


@pytest.fixture
def viewer_membership(db, viewer_role):
    from tests.factories import UserFactory
    user = UserFactory()
    store = _make_store()
    membership = StoreMembership.objects.create(
        user=user, store=store, role=viewer_role, is_active=True,
    )
    return user, store, membership


@pytest.fixture
def plan_with_features(db):
    """A 'Growth'-style plan with two features."""
    plan = SubscriptionPlan.objects.create(
        name="Test Growth", slug="test-growth", price=49,
        max_users=10, max_stores=1, max_products=5000,
    )
    f1 = Feature.objects.create(code="customer_management", name="Customer Mgmt")
    f2 = Feature.objects.create(code="marketing_campaigns", name="Marketing")
    PlanFeature.objects.create(plan=plan, feature=f1)
    PlanFeature.objects.create(plan=plan, feature=f2)
    return plan, [f1, f2]


@pytest.fixture
def active_subscription(db, plan_with_features):
    from django.utils import timezone
    plan, _ = plan_with_features
    store = _make_store()
    sub = Subscription.objects.create(
        store=store, plan=plan, status=SUB_ACTIVE,
        starts_at=timezone.now(),
        current_period_end=timezone.now() + timezone.timedelta(days=30),
    )
    return store, sub, plan
