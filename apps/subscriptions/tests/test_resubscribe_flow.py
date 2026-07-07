"""End-to-end tests for the post-cancel re-subscribe flow.

Reproduces the user's reported scenario:
1. Cancel subscription
2. Click plan on /plans/ -> redirects to /checkout/<slug>/?trial=true
3. Click Subscribe button on checkout page -> POST /checkout/<slug>/
4. Verify the row is active again, the dashboard banner is gone, and
   /filter reports the new plan's max_seats (not null).

The bug was: ``subscription_checkout`` POST checked
``live_subscription.is_active()``. After cancel, that's False, so the
view treated it as first-time-signup: wrote ``pending_plan_slug`` and
redirected to /welcome/ without reactivating the row. After the fix,
``subscription_checkout`` uses ``find_user_subscription_row`` and
routes through ``change_plan`` whenever a row exists (regardless of
status); ``change_plan`` itself detects the canceled state and
reactivates.
"""
from __future__ import annotations

import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.permissions.models import (
    Subscription,
    SubscriptionPlan,
    StoreMembership,
    Role,
)
from apps.accounts.models import Tenant
from apps.stores.models import Store
from apps.subscriptions.services import (
    cancel_subscription,
    find_user_subscription_row,
    get_active_subscription,
)
from apps.permissions.services import plan_limit
from tests.factories import UserFactory


pytestmark = pytest.mark.django_db


def _seed_owner_membership(user, store):
    """Make the user a member of the store as the system-wide owner role,
    so the dashboard renders normally (the dashboard's
    subscription_needs_attention branch fires when the user has any
    active membership, even if the sub itself is gone).
    """
    from apps.permissions.seeders.roles_seeder import RolesSeeder
    from apps.permissions.seeders.permissions_seeder import (
        RolePermissionsSeeder,
    )

    RolesSeeder().run()
    RolePermissionsSeeder(verbosity=0).run()
    owner_role = Role.objects.get(slug="store-owner", store__isnull=True)
    StoreMembership.objects.create(
        user=user, store=store, role=owner_role, is_active=True,
    )


# ---------------------------------------------------------------------------
# find_user_subscription_row — predicate used by re-subscribe flows
# ---------------------------------------------------------------------------
class TestFindUserSubscriptionRow:
    """Returns the user's row regardless of state, used by re-subscribe
    flows (subscription_checkout, update_subscription_plan) to find a
    canceled row that's ready to be revived by ``change_plan``.
    """

    def test_returns_active_row(self):
        user = UserFactory()
        tenant = Tenant.objects.create(
            owner=user, slug='t1', name='t1', is_active=True,
        )
        store = Store.objects.create(name='S', tenant=tenant)
        plan = SubscriptionPlan.objects.create(
            name='Starter', slug='starter', price=29,
            max_users=3, max_stores=1,
        )
        sub = Subscription.objects.create(
            store=store, plan=plan, status='active',
            starts_at=timezone.now(),
            current_period_end=timezone.now() + timezone.timedelta(days=30),
        )
        result = find_user_subscription_row(user)
        assert result is not None
        assert result.id == sub.id

    def test_returns_canceled_row(self):
        """A canceled row is still the user's subscription — the helper
        must return it so re-subscribe flows can reactivate it."""
        user = UserFactory()
        tenant = Tenant.objects.create(
            owner=user, slug='t1', name='t1', is_active=True,
        )
        store = Store.objects.create(name='S', tenant=tenant)
        plan = SubscriptionPlan.objects.create(
            name='Starter', slug='starter', price=29,
            max_users=3, max_stores=1,
        )
        sub = Subscription.objects.create(
            store=store, plan=plan, status='active',
            starts_at=timezone.now(),
            current_period_end=timezone.now() + timezone.timedelta(days=30),
        )

        cancel_subscription(sub, cancel_at_period_end=False, actor=user)
        sub.refresh_from_db()
        assert sub.status == "canceled"

        result = find_user_subscription_row(user)
        assert result is not None, (
            "find_user_subscription_row should return canceled rows so "
            "re-subscribe flows can revive them. Returning None forces "
            "the view into the first-time-signup branch."
        )
        assert result.id == sub.id

    def test_returns_none_for_first_time_signup(self):
        user = UserFactory()
        result = find_user_subscription_row(user)
        assert result is None


# ---------------------------------------------------------------------------
# subscription_checkout POST — re-subscribe end-to-end
# ---------------------------------------------------------------------------
def test_post_cancel_checkout_post_actually_subscribes():
    """Reproduce the exact user flow: canceled user clicks a plan, POSTs
    to checkout, expecting subscription to flip back to active."""
    user = UserFactory()

    tenant = Tenant.objects.create(
        owner=user, slug='t1', name='t1', is_active=True,
    )
    store = Store.objects.create(name='S', tenant=tenant)
    starter = SubscriptionPlan.objects.create(
        name='Starter', slug='starter', price=29,
        max_users=3, max_stores=1,
    )
    pro = SubscriptionPlan.objects.create(
        name='Professional', slug='professional', price=149,
        max_users=10, max_stores=2,
    )

    sub = Subscription.objects.create(
        store=store, plan=starter, status='active',
        starts_at=timezone.now(),
        current_period_end=timezone.now() + timezone.timedelta(days=30),
    )
    _seed_owner_membership(user, store)

    # 1. Cancel (immediate)
    cancel_subscription(sub, cancel_at_period_end=False, actor=user)
    sub.refresh_from_db()
    assert sub.status == "canceled"

    # 2. POST to /checkout/professional/ — the actual user flow.
    from django.test import Client
    c = Client()
    c.force_login(user)
    res = c.post(
        "/subscriptions/checkout/professional/",
        data={"start_trial": "false"},
    )

    sub.refresh_from_db()
    cache.clear()

    assert res.status_code in (200, 302), (
        f"Unexpected checkout response {res.status_code}: {res.content!r}"
    )
    assert sub.status == "active", (
        f"After checkout POST, expected sub.status='active', got "
        f"'{sub.status}'. The checkout view treats a canceled user as "
        f"first-time signup and writes pending_plan_slug without "
        f"activating the existing row."
    )
    assert sub.plan.slug == "professional"
    assert get_active_subscription(store) is not None
    assert plan_limit(store, 'max_users') == 10

    # The team-management filter endpoint computes max_seats from
    # plan_limit; with the row active and pointing at the Pro plan,
    # the response should now show max_seats == 10.
    res2 = c.get(f"/settings/team/{store.id}/filter/")
    assert res2.status_code == 200
    body = res2.json()
    assert body["stats"]["max_seats"] == 10, (
        f"After re-subscribe, /filter should report max_seats=10, got "
        f"{body['stats'].get('max_seats')!r}."
    )

    # Dashboard banner should NOT render after re-subscription. The
    # ``subscription_needs_attention and not user_subscription`` guard
    # is now False (the sub is active again).
    res3 = c.get("/dashboard/")
    assert res3.status_code == 200
    assert b"Your subscription is no longer active" not in res3.content, (
        "Dashboard banner still shows after re-subscribe — "
        "resolve_user_subscription is returning None for an active row."
    )
