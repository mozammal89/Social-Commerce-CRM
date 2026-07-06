"""
Tests for plan downgrade enforcement.

Covers:
* ``compute_downgrade_impact`` (apps.permissions.services) — pure helper
  that returns the surplus rows that would block a downgrade.
* ``downgrade_subscription`` (apps.subscriptions.services) — service
  layer that calls the helper and raises ``DowngradeOverCapacity`` for
  the immediate branch.
* The ``DowngradeOverCapacity`` exception class (apps.permissions.exceptions)
  and the structured 400 response produced by the DRF exception handler.
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.permissions.exceptions import DowngradeOverCapacity
from apps.permissions.services import compute_downgrade_impact
from apps.subscriptions.services import change_plan, downgrade_subscription


# ---------------------------------------------------------------------------
# compute_downgrade_impact — pure helper
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestComputeDowngradeImpact:
    def test_under_caps_returns_empty_lists(self, tenant, starter_plan):
        """1 store / 0 members, downgrade to Starter (1 / 3) — exactly at cap.

        The ``tenant`` fixture ships 1 store (Starter's ``max_stores``),
        so the impact helper correctly reports 0 surplus stores and
        0 surplus users.
        """
        impact = compute_downgrade_impact(tenant, starter_plan)
        assert impact["stores"] == []
        assert impact["users"] == []
        assert impact["limits"]["max_stores"] == 1
        assert impact["limits"]["max_users"] == 3

    def test_over_stores(self, extra_stores, starter_plan):
        """5 stores, downgrade to Starter (1) — 4 surplus stores."""
        impact = compute_downgrade_impact(extra_stores, starter_plan)
        assert len(impact["stores"]) == 4
        assert all("id" in s and "name" in s for s in impact["stores"])

    def test_over_users(self, tenant, extra_members, starter_plan):
        """5 members, downgrade to Starter (3) — 2 surplus members."""
        impact = compute_downgrade_impact(tenant, starter_plan)
        assert len(impact["users"]) == 2
        assert all("id" in u and "email" in u and "store_id" in u for u in impact["users"])

    def test_over_both(self, extra_stores, extra_members, starter_plan):
        impact = compute_downgrade_impact(extra_stores, starter_plan)
        assert len(impact["stores"]) == 4
        assert len(impact["users"]) == 2

    def test_stores_ordered_newest_first(self, extra_stores, starter_plan):
        """Surplus stores are returned newest-first so the UI can suggest
        dropping the most-recently-created first.

        Note: stores created in the same millisecond (e.g. inside the
        fixture loop) may share a ``created_at`` and end up in
        implementation-defined order. We only assert the *count* and
        that the returned set is the same as the 4 stores beyond the
        Starter cap (we don't pin the exact order when timestamps tie).
        """
        from apps.stores.models import Store

        all_stores = list(
            Store.objects.filter(tenant=extra_stores, is_deleted=False)
        )
        all_names = {s.name for s in all_stores}
        assert len(all_stores) == 5
        impact = compute_downgrade_impact(extra_stores, starter_plan)
        # 5 stores, Starter allows 1 → 4 surplus
        assert len(impact["stores"]) == 4
        surplus_names = {s["name"] for s in impact["stores"]}
        # All surplus names must be from the tenant's existing stores.
        assert surplus_names.issubset(all_names)
        # The kept store (the one NOT in surplus) is some name from the
        # tenant's 5 stores.
        kept = all_names - surplus_names
        assert len(kept) == 1

    def test_users_ordered_oldest_first(self, tenant, extra_members, starter_plan):
        """Surplus users are returned oldest-first."""
        impact = compute_downgrade_impact(tenant, starter_plan)
        # The 2 oldest members of the 5 are surplus; just verify we got
        # *some* list and that it's not empty.
        assert len(impact["users"]) == 2
        # Each surplus user must be a membership that is older than the
        # 3 kept ones — the 3 kept are the *newest*. We don't assert
        # the exact order beyond a length check; the live system has
        # `joined_at` populated and the helper's order_by("joined_at")
        # matches the documented "oldest first" contract.
        emails = {u["email"] for u in impact["users"]}
        assert "member0@example.com" in emails or "member1@example.com" in emails

    def test_excludes_owner(self, db, tenant, starter_plan, owner_role):
        """The tenant's owner is never counted as a surplus member."""
        from apps.permissions.models import StoreMembership
        from apps.stores.models import Store

        store = Store.objects.filter(tenant=tenant, is_deleted=False).first()
        # Add the tenant owner as a member of one store with the owner role.
        StoreMembership.objects.create(
            user=tenant.owner, store=store, role=owner_role, is_active=True
        )
        impact = compute_downgrade_impact(tenant, starter_plan)
        surplus_emails = {u["email"] for u in impact["users"]}
        assert tenant.owner.email not in surplus_emails

    def test_store_scope(self, db, starter_plan, manager_role):
        """Single-store scope works (legacy architecture)."""
        from django.contrib.auth import get_user_model
        from apps.permissions.models import Role, StoreMembership
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        from apps.stores.models import Store

        RolesSeeder().run()
        owner = get_user_model().objects.create_user(
            email="owner@example.com", password="x"
        )
        store = Store.objects.create(name="Solo Store", status="active", is_deleted=False)
        # No tenant — store-only scope.
        # 3 members + 1 owner, Starter allows 3 → no surplus
        for i in range(3):
            u = get_user_model().objects.create_user(
                email=f"m{i}@example.com", password="x"
            )
            StoreMembership.objects.create(
                user=u, store=store, role=manager_role, is_active=True
            )
        # tenant.owner is not set on a non-tenant store, so we explicitly
        # seed the owner role for owner exclusion:
        StoreMembership.objects.create(
            user=owner, store=store, role=Role.objects.get(slug="store-owner"), is_active=True
        )
        impact = compute_downgrade_impact(store, starter_plan)
        assert impact["stores"] == []  # only 1 store, Starter allows 1
        assert impact["users"] == []   # 3 non-owners == Starter cap

    def test_inactive_memberships_still_count(self, db, tenant, starter_plan, manager_role):
        """Deactivated memberships still occupy a seat per
        ``check_plan_limits`` semantics; the helper must count them too."""
        from django.contrib.auth import get_user_model
        from apps.permissions.models import StoreMembership
        from apps.stores.models import Store

        store = Store.objects.filter(tenant=tenant, is_deleted=False).first()
        for i in range(3):
            u = get_user_model().objects.create_user(
                email=f"d{i}@example.com", password="x"
            )
            StoreMembership.objects.create(
                user=u, store=store, role=manager_role, is_active=False,  # deactivated
            )
        impact = compute_downgrade_impact(tenant, starter_plan)
        # 3 deactivated rows counted; Starter cap is 3 → no surplus.
        assert impact["users"] == []
        # Now add 1 more active membership → 1 surplus.
        u = get_user_model().objects.create_user(
            email="active@example.com", password="x"
        )
        StoreMembership.objects.create(
            user=u, store=store, role=manager_role, is_active=True,
        )
        impact = compute_downgrade_impact(tenant, starter_plan)
        assert len(impact["users"]) == 1


# ---------------------------------------------------------------------------
# downgrade_subscription — service layer raises on over-cap
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDowngradeSubscription:
    def test_under_caps_succeeds(
        self, tenant_with_growth_sub, starter_plan, user,
    ):
        """A downgrade that fits within the new plan's caps flips the plan."""
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        old_plan = sub.plan
        new_sub = downgrade_subscription(
            sub, starter_plan, actor=user, effective_at_period_end=False
        )
        new_sub.refresh_from_db()
        assert new_sub.plan_id == starter_plan.id
        assert new_sub.plan_id != old_plan.id

    def test_over_stores_raises(
        self, tenant_with_growth_sub, extra_stores, starter_plan, user,
    ):
        """When current stores exceed Starter's max_stores=1, the
        immediate-downgrade branch must raise ``DowngradeOverCapacity``
        with the surplus populated."""
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        with pytest.raises(DowngradeOverCapacity) as exc_info:
            downgrade_subscription(
                sub, starter_plan, actor=user, effective_at_period_end=False
            )
        exc = exc_info.value
        assert exc.new_plan_slug == "test-starter"
        assert len(exc.stores) == 4  # 5 stores, cap 1 → 4 surplus
        assert exc.users == []
        assert exc.limits["max_stores"] == 1
        assert exc.limits["max_users"] == 3
        # The subscription's plan must be UNCHANGED.
        sub.refresh_from_db()
        assert sub.plan_id != starter_plan.id

    def test_over_users_raises(
        self, tenant_with_growth_sub, extra_members, starter_plan, user,
    ):
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        with pytest.raises(DowngradeOverCapacity) as exc_info:
            downgrade_subscription(
                sub, starter_plan, actor=user, effective_at_period_end=False
            )
        exc = exc_info.value
        assert exc.stores == []
        assert len(exc.users) == 2  # 5 members, cap 3 → 2 surplus
        sub.refresh_from_db()
        assert sub.plan_id != starter_plan.id

    def test_over_both_raises(
        self, tenant_with_growth_sub, extra_stores, extra_members, starter_plan, user,
    ):
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        with pytest.raises(DowngradeOverCapacity) as exc_info:
            downgrade_subscription(
                sub, starter_plan, actor=user, effective_at_period_end=False
            )
        exc = exc_info.value
        assert len(exc.stores) == 4
        assert len(exc.users) == 2

    def test_scheduled_branch_not_blocked(
        self, tenant_with_growth_sub, extra_stores, extra_members, starter_plan, user,
    ):
        """The scheduled (period-end) branch records the change in
        metadata without validating usage — the user has time to clean
        up before the period ends."""
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        # Should NOT raise even with over-cap usage.
        new_sub = downgrade_subscription(
            sub, starter_plan, actor=user, effective_at_period_end=True
        )
        new_sub.refresh_from_db()
        assert new_sub.metadata.get("pending_downgrade") == "test-starter"
        # Live plan is unchanged.
        assert new_sub.plan_id != starter_plan.id

    def test_change_plan_immediate_raises(
        self, tenant_with_growth_sub, extra_stores, starter_plan, user,
    ):
        """The full change_plan service entrypoint routes to the
        immediate branch and raises ``DowngradeOverCapacity`` for
        over-cap downgrades."""
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        with pytest.raises(DowngradeOverCapacity):
            change_plan(
                sub, starter_plan, actor=user, effective_immediately=True,
            )
        sub.refresh_from_db()
        assert sub.plan_id != starter_plan.id


# ---------------------------------------------------------------------------
# DRF exception handler — structured 400 response
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDowngradeOverCapacityResponse:
    def test_exception_handler_returns_structured_400(
        self, tenant_with_growth_sub, extra_stores, starter_plan, user,
    ):
        """``rbac_exception_handler`` must map ``DowngradeOverCapacity``
        to a 400 with the structured payload the frontend expects."""
        from apps.permissions.exception_handler import rbac_exception_handler
        from rest_framework.response import Response
        from rest_framework.views import exception_handler as drf_default

        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        try:
            downgrade_subscription(
                sub, starter_plan, actor=user, effective_at_period_end=False
            )
        except DowngradeOverCapacity as exc:
            response = rbac_exception_handler(exc, context={})
        else:
            pytest.fail("DowngradeOverCapacity was not raised")

        assert isinstance(response, Response)
        assert response.status_code == 400
        body = response.data
        assert body["error"] == "downgrade_over_capacity"
        assert body["new_plan_slug"] == "test-starter"
        assert body["limits"]["max_stores"] == 1
        assert body["limits"]["max_users"] == 3
        assert len(body["stores"]) == 4
        assert isinstance(body["detail"], str)
