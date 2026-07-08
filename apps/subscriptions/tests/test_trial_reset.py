"""
Tests for trial-clock reset on plan change.

When a ``trialing`` user picks a different plan via ``change_plan``,
the existing trial clock (a) was tied to the *old* plan and (b) was
counting down to expiry that no longer matches the user's intent now
that they're on a new plan. Without a reset, the user sees:

  Plan: Growth Plan (new)
  Trial Ends: Jul 9, 2026 (Starter's old trial clock)
  Banner:  "Your trial ends tomorrow" (Starter's banner)

That's confusing — the user thinks they're paying for Growth but the
trial countdown is for Starter. This file locks down the fix in
``apps.subscriptions.services.change_plan``:

* ``trialing`` user picking a plan that *does* offer a trial →
  ``trial_ends_at`` re-anchored to ``now + new_plan.trial_days``,
  status stays ``trialing``.
* ``trialing`` user picking a plan with ``trial_days=0`` →
  status bumped to ``active``, ``trial_ends_at`` cleared,
  ``current_period_end`` set to ``now + 30d``.
* Non-trialing users (active, canceled, expired) → unchanged
  behavior, governed by the existing ``needs_reactivate`` branch.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.subscriptions.constants import STATUS_ACTIVE, STATUS_TRIALING


# ---------------------------------------------------------------------------
# change_plan: trialing source
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestChangePlanResetsTrialClock:
    """Plan change from a ``trialing`` source re-anchors the trial clock
    to the new plan's trial window — or bumps to ``active`` when the
    new plan doesn't offer a trial."""

    def _make_user_with_trial_sub(
        self, growth_plan, trial_ends_in_days=1,
    ):
        """A user + tenant + trialing subscription on the Starter plan,
        with ``trial_ends_at`` set to ``trial_ends_in_days`` from now."""
        from django.contrib.auth import get_user_model
        from apps.accounts.models import Tenant
        from apps.subscriptions.models import Subscription, SubscriptionPlan

        # Build a Starter plan (cheaper than Growth) so an upgrade
        # is possible.
        starter, _ = SubscriptionPlan.objects.get_or_create(
            slug="test-starter-reset",
            defaults={
                "name": "Test Starter",
                "price": 19,
                "currency": "USD",
                "billing_period": "monthly",
                "trial_days": 14,
                "max_users": 3,
                "max_stores": 1,
                "max_products": 500,
                "max_orders_per_month": 1000,
                "max_warehouses": 1,
                "is_active": True,
                "is_public": True,
            },
        )

        User = get_user_model()
        user = User.objects.create_user(
            email="trial-reset@example.com", password="x",
        )
        tenant = Tenant.objects.create(
            name="Trial Reset Tenant",
            slug="trial-reset",
            owner=user,
            is_active=True,
        )
        sub = Subscription.objects.create(
            tenant=tenant,
            plan=starter,
            status=STATUS_TRIALING,
            starts_at=timezone.now() - timedelta(days=14),
            trial_ends_at=timezone.now() + timedelta(days=trial_ends_in_days),
        )
        return user, tenant, sub, starter

    def test_trial_clock_resets_to_new_plan_trial_days(
        self, growth_plan,
    ):
        """A trialing user picking Growth (which has its own 14-day
        trial) gets a fresh ``trial_ends_at`` ≈14 days from now, NOT
        the old Starter trial clock."""
        from apps.subscriptions.services import change_plan

        _user, _tenant, sub, _starter = self._make_user_with_trial_sub(
            growth_plan, trial_ends_in_days=1,
        )
        # Pre-condition: trial ends in ~1 day (Starter's old clock).
        original_end = sub.trial_ends_at
        assert (original_end - timezone.now()).days <= 1

        change_plan(sub, growth_plan)

        sub.refresh_from_db()
        # Plan was swapped.
        assert sub.plan == growth_plan
        # Status stays trialing (still in the trial window).
        assert sub.status == STATUS_TRIALING
        # trial_ends_at was re-anchored — NOT the original 1-day clock.
        # Growth's trial_days defaults to 14, so the new end should
        # be ~14 days out.
        assert sub.trial_ends_at != original_end
        days_remaining = (sub.trial_ends_at - timezone.now()).days
        assert 13 <= days_remaining <= 14

    def test_trial_clock_reset_clears_warning_banner(
        self, growth_plan,
    ):
        """End-to-end: after the reset, ``trial_days_remaining`` falls
        outside the banner-firing range (was 1, now ~14), so the
        manage-page banner no longer renders."""
        from apps.subscriptions.services import change_plan

        _user, _tenant, sub, _starter = self._make_user_with_trial_sub(
            growth_plan, trial_ends_in_days=1,
        )
        # Pre-fix this would still show "Your trial ends tomorrow".
        change_plan(sub, growth_plan)

        sub.refresh_from_db()
        # Now > 3 days remaining → banner shouldn't fire.
        days = (sub.trial_ends_at - timezone.now()).days
        assert days > 3

    def test_trial_user_picking_no_trial_plan_becomes_active(
        self, db,
    ):
        """If the user picks a plan whose ``trial_days`` is 0, they
        immediately become ``active`` (not trialing), with a fresh
        ``current_period_end`` and no trial banner."""
        from django.contrib.auth import get_user_model
        from apps.accounts.models import Tenant
        from apps.subscriptions.models import Subscription, SubscriptionPlan
        from apps.subscriptions.services import change_plan

        # Source: a trialing subscription on Starter.
        starter, _ = SubscriptionPlan.objects.get_or_create(
            slug="test-starter-no-trial-reset",
            defaults={
                "name": "Starter (no-trial test)",
                "price": 19,
                "currency": "USD",
                "billing_period": "monthly",
                "trial_days": 14,
                "max_users": 3,
                "max_stores": 1,
                "max_products": 500,
                "max_orders_per_month": 1000,
                "max_warehouses": 1,
                "is_active": True,
                "is_public": True,
            },
        )
        # Destination: a higher-priced plan with NO trial.
        no_trial, _ = SubscriptionPlan.objects.get_or_create(
            slug="test-pro-no-trial",
            defaults={
                "name": "Pro (no trial)",
                "price": 99,
                "currency": "USD",
                "billing_period": "monthly",
                "trial_days": 0,  # <-- the test trigger
                "max_users": 25,
                "max_stores": 5,
                "max_products": 5000,
                "max_orders_per_month": 20000,
                "max_warehouses": 5,
                "is_active": True,
                "is_public": True,
            },
        )

        User = get_user_model()
        user = User.objects.create_user(
            email="trial-reset-no-trial@example.com", password="x",
        )
        tenant = Tenant.objects.create(
            name="No Trial Tenant", slug="no-trial", owner=user, is_active=True,
        )
        sub = Subscription.objects.create(
            tenant=tenant,
            plan=starter,
            status=STATUS_TRIALING,
            starts_at=timezone.now(),
            trial_ends_at=timezone.now() + timedelta(days=2),
        )

        change_plan(sub, no_trial)

        sub.refresh_from_db()
        assert sub.status == STATUS_ACTIVE
        assert sub.trial_ends_at is None
        assert sub.current_period_end is not None
        # Fresh 30-day billing period.
        days = (sub.current_period_end - timezone.now()).days
        assert 29 <= days <= 30

    def test_non_trial_source_unaffected(
        self, tenant_with_growth_sub,
    ):
        """The trial-reset branch must NOT fire for active / canceled /
        expired source subs — those go through ``needs_reactivate`` /
        the normal upgrade/downgrade path."""
        from apps.subscriptions.services import change_plan
        from apps.subscriptions.models import SubscriptionPlan

        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        # tenant_with_growth_sub fixture has status='active', no
        # trial_ends_at — confirm pre-conditions.
        assert sub.status == STATUS_ACTIVE
        assert sub.trial_ends_at is None

        # Downgrade path (Growth → Starter) so the price-comparison
        # branch executes.
        starter, _ = SubscriptionPlan.objects.get_or_create(
            slug="test-starter-downgrade-reset",
            defaults={
                "name": "Starter (downgrade test)",
                "price": 19,
                "currency": "USD",
                "billing_period": "monthly",
                "trial_days": 14,
                "max_users": 3,
                "max_stores": 1,
                "max_products": 500,
                "max_orders_per_month": 1000,
                "max_warehouses": 1,
                "is_active": True,
                "is_public": True,
            },
        )

        change_plan(sub, starter)
        sub.refresh_from_db()
        # Status remains active (the user is paying for the new plan,
        # not entering a trial of it).
        assert sub.status == STATUS_ACTIVE
        # trial_ends_at was NOT touched (the trial-reset branch didn't
        # run because source wasn't trialing).
        assert sub.trial_ends_at is None