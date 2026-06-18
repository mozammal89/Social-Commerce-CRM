"""Tests for subscription / feature gating."""

from __future__ import annotations

import pytest

from apps.permissions.constants import (
    SUB_ACTIVE,
    SUB_TRIALING,
    SUB_CANCELED,
)
from apps.permissions.models import (
    Feature,
    PlanFeature,
    Subscription,
    SubscriptionPlan,
)
from apps.permissions.resolver import PermissionResolver
from apps.permissions.services import (
    assert_within_plan_limit,
    plan_limit,
    store_has_feature,
    user_has_feature,
)


@pytest.mark.django_db
class TestFeatureGating:
    def test_store_has_feature_returns_true_when_plan_has_it(
        self, active_subscription,
    ):
        store, sub, plan = active_subscription
        assert store_has_feature(store, "customer_management") is True
        assert store_has_feature(store, "marketing_campaigns") is True

    def test_store_has_feature_returns_false_when_plan_lacks_it(
        self, active_subscription,
    ):
        store, _, _ = active_subscription
        assert store_has_feature(store, "multi_warehouse") is False

    def test_user_has_feature_requires_membership(self, active_subscription):
        from tests.factories import UserFactory
        from apps.permissions.models import StoreMembership
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        RolesSeeder().run()
        from apps.permissions.models import Role

        store, sub, plan = active_subscription
        u = UserFactory()
        # No membership yet.
        assert user_has_feature(u, store, "customer_management") is False
        # Add membership.
        StoreMembership.objects.create(
            user=u, store=store,
            role=Role.objects.get(slug="viewer"),
            is_active=True,
        )
        assert user_has_feature(u, store, "customer_management") is True

    def test_canceled_subscription_loses_features(
        self, active_subscription,
    ):
        store, sub, plan = active_subscription
        sub.status = SUB_CANCELED
        sub.save()
        assert store_has_feature(store, "customer_management") is False

    def test_plan_limit_helper(self, active_subscription):
        store, _, _ = active_subscription
        assert plan_limit(store, "max_users") == 10
        # No plan = no limit.
        from apps.stores.models import Store
        s2 = Store.objects.create(name="NoSub", status="active")
        assert plan_limit(s2, "max_users") is None

    def test_assert_within_plan_limit_passes(self, active_subscription):
        store, _, _ = active_subscription
        # 5 of 10 → ok.
        assert_within_plan_limit(store, "max_users", 5)

    def test_assert_within_plan_limit_raises(self, active_subscription):
        from apps.permissions.exceptions import PlanLimitExceeded
        store, _, _ = active_subscription
        with pytest.raises(PlanLimitExceeded):
            assert_within_plan_limit(store, "max_users", 100)


@pytest.mark.django_db
class TestSubscriptionStatus:
    def test_trial_with_future_end_is_active(self):
        from django.utils import timezone
        from datetime import timedelta
        from apps.stores.models import Store

        store = Store.objects.create(name="Trial Store", status="active")
        plan = SubscriptionPlan.objects.create(
            name="Trial Plan", slug="trial-plan", price=0,
            max_users=5, max_stores=1, max_products=10,
        )
        sub = Subscription.objects.create(
            store=store, plan=plan, status=SUB_TRIALING,
            starts_at=timezone.now(),
            trial_ends_at=timezone.now() + timedelta(days=7),
        )
        assert sub.is_active() is True

    def test_trial_with_past_end_is_not_active(self):
        from django.utils import timezone
        from datetime import timedelta
        from apps.stores.models import Store

        store = Store.objects.create(name="Trial Store Old", status="active")
        plan = SubscriptionPlan.objects.create(
            name="Trial Plan", slug="trial-plan-old", price=0,
            max_users=5, max_stores=1, max_products=10,
        )
        sub = Subscription.objects.create(
            store=store, plan=plan, status=SUB_TRIALING,
            starts_at=timezone.now() - timedelta(days=30),
            trial_ends_at=timezone.now() - timedelta(days=1),
        )
        assert sub.is_active() is False
