"""
Tests for the service-layer helpers in ``apps.permissions.services``.

These tests focus on the membership operations, role cloning, plan-limit
helpers, and feature gating facade that views and admin actions call.
"""

from __future__ import annotations

import pytest

from apps.permissions import services
from apps.permissions.constants import (
    MODIFIER_DENY,
    MODIFIER_GRANT,
    ROLE_VIEWER,
)
from apps.permissions.exceptions import PlanLimitExceeded
from apps.permissions.models import (
    PlanFeature,
    Role,
    StoreMembership,
    Subscription,
)
from apps.permissions.tests.conftest import _make_store


@pytest.mark.django_db
class TestStoreHasFeature:
    def test_no_store_returns_false(self):
        assert services.store_has_feature(None, "any") is False

    def test_no_subscription_returns_false(self, db):
        store = _make_store()
        assert services.store_has_feature(store, "any") is False

    def test_inactive_subscription_returns_false(self, db, plan_with_features):
        plan, _features = plan_with_features
        from django.utils import timezone
        store = _make_store()
        Subscription.objects.create(
            store=store, plan=plan, status="expired",
            starts_at=timezone.now(),
        )
        assert services.store_has_feature(store, "customer_management") is False

    def test_active_subscription_with_feature(self, active_subscription):
        store, _sub, _plan = active_subscription
        assert services.store_has_feature(store, "customer_management") is True

    def test_active_subscription_without_feature(self, active_subscription):
        store, _sub, _plan = active_subscription
        assert services.store_has_feature(store, "nonexistent_feature") is False


@pytest.mark.django_db
class TestUserHasFeature:
    def test_anonymous_user_returns_false(self, active_subscription):
        store, _sub, _plan = active_subscription
        from django.contrib.auth.models import AnonymousUser
        assert services.user_has_feature(AnonymousUser(), store, "customer_management") is False

    def test_no_store_returns_false(self, db):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create(email="u@x.com")
        assert services.user_has_feature(user, None, "x") is False

    def test_superuser_with_active_sub_passes(self, active_subscription):
        from django.contrib.auth import get_user_model
        store, _sub, _plan = active_subscription
        user = get_user_model().objects.create_superuser(email="super@x.com", password="x")
        assert services.user_has_feature(user, store, "customer_management") is True

    def test_active_member_passes(self, active_subscription, manager_membership):
        store, _sub, _plan = active_subscription
        user, _user_store, _membership = manager_membership
        # Note: user is a member of a DIFFERENT store here. Need to bind them.
        StoreMembership.objects.create(
            user=user, store=store, role=Role.objects.get(slug=ROLE_VIEWER),
            is_active=True,
        )
        assert services.user_has_feature(user, store, "customer_management") is True

    def test_non_member_returns_false(self, active_subscription, manager_membership):
        store, _sub, _plan = active_subscription
        user, _user_store, _membership = manager_membership
        # user is not a member of `store`
        assert services.user_has_feature(user, store, "customer_management") is False


@pytest.mark.django_db
class TestUserRolesInStore:
    def test_none_inputs_return_empty(self, db):
        assert services.user_roles_in_store(None, None) == []

    def test_returns_active_roles_ordered_by_level_desc(
        self, db, owner_role, manager_role,
    ):
        from tests.factories import UserFactory
        user = UserFactory()
        store = _make_store()
        StoreMembership.objects.create(user=user, store=store, role=manager_role, is_active=True)
        StoreMembership.objects.create(user=user, store=store, role=owner_role, is_active=True)
        StoreMembership.objects.create(
            user=user, store=store,
            role=Role.objects.create(name="Inactive", slug="inactive", store=store, is_system=False),
            is_active=False,
        )
        roles = services.user_roles_in_store(user, store)
        slugs = [r.slug for r in roles]
        # Owner first (level 100), then manager (60). Inactive excluded.
        assert slugs == ["store-owner", "manager"]


@pytest.mark.django_db
class TestCloneRole:
    def test_clone_creates_non_system_role(self, db, owner_role):
        clone = services.clone_role(
            owner_role, new_name="Co-Owner", new_slug="co-owner",
        )
        assert clone.is_system is False
        assert clone.name == "Co-Owner"
        assert clone.slug == "co-owner"
        assert clone.inherits_from_id == owner_role.id

    def test_clone_copies_role_permissions(self, db, owner_role, permissions):
        from apps.permissions.models import RolePermission
        perm = permissions["orders.view"]
        RolePermission.objects.create(
            role=owner_role, permission=perm, modifier=MODIFIER_GRANT,
        )
        clone = services.clone_role(
            owner_role, new_name="Co-Owner", new_slug="co-owner",
        )
        clone_perms = set(
            clone.role_permissions.values_list("permission__code", "modifier")
        )
        assert ("orders.view", "grant") in clone_perms

    def test_clone_copies_deny_modifier(self, db, owner_role, permissions):
        from apps.permissions.models import RolePermission
        perm = permissions["orders.delete"]
        RolePermission.objects.create(
            role=owner_role, permission=perm, modifier=MODIFIER_DENY,
        )
        clone = services.clone_role(
            owner_role, new_name="Co-Owner", new_slug="co-owner",
        )
        assert clone.role_permissions.get(permission=perm).modifier == MODIFIER_DENY


@pytest.mark.django_db
class TestPlanLimitHelpers:
    def test_assert_within_plan_limit_no_sub_raises(self, db):
        store = _make_store()
        with pytest.raises(PlanLimitExceeded):
            services.assert_within_plan_limit(store, "max_users", 1)

    def test_assert_within_plan_limit_inactive_sub_raises(self, db, plan_with_features):
        from django.utils import timezone
        plan, _ = plan_with_features
        store = _make_store()
        Subscription.objects.create(
            store=store, plan=plan, status="expired",
            starts_at=timezone.now(),
        )
        with pytest.raises(PlanLimitExceeded):
            services.assert_within_plan_limit(store, "max_users", 1)

    def test_assert_within_plan_limit_under_cap_ok(
        self, db, plan_with_features,
    ):
        from django.utils import timezone
        plan, _ = plan_with_features
        store = _make_store()
        Subscription.objects.create(
            store=store, plan=plan, status="active",
            starts_at=timezone.now(),
            current_period_end=timezone.now() + timezone.timedelta(days=30),
        )
        # 5 < 10 cap → no raise
        services.assert_within_plan_limit(store, "max_users", 5)

    def test_assert_within_plan_limit_at_cap_raises(
        self, db, plan_with_features,
    ):
        from django.utils import timezone
        plan, _ = plan_with_features
        store = _make_store()
        Subscription.objects.create(
            store=store, plan=plan, status="active",
            starts_at=timezone.now(),
            current_period_end=timezone.now() + timezone.timedelta(days=30),
        )
        with pytest.raises(PlanLimitExceeded) as exc:
            services.assert_within_plan_limit(store, "max_users", 10)
        assert exc.value.cap == 10

    def test_plan_limit_returns_cap_value(self, db, plan_with_features):
        from django.utils import timezone
        plan, _ = plan_with_features
        store = _make_store()
        Subscription.objects.create(
            store=store, plan=plan, status="active",
            starts_at=timezone.now(),
            current_period_end=timezone.now() + timezone.timedelta(days=30),
        )
        assert services.plan_limit(store, "max_users") == 10

    def test_plan_limit_returns_none_when_no_sub(self, db):
        store = _make_store()
        assert services.plan_limit(store, "max_users") is None


@pytest.mark.django_db
class TestMembershipOperations:
    def test_add_member_creates_membership(self, db, manager_role):
        from tests.factories import UserFactory
        user = UserFactory()
        store = _make_store()
        m = services.add_member(user, store, manager_role)
        assert m.user_id == user.id
        assert m.store_id == store.id
        assert m.is_active is True

    def test_add_member_is_idempotent(self, db, manager_role):
        from tests.factories import UserFactory
        user = UserFactory()
        store = _make_store()
        m1 = services.add_member(user, store, manager_role)
        m2 = services.add_member(user, store, manager_role)
        assert m1.id == m2.id
        assert StoreMembership.objects.filter(
            user=user, store=store, role=manager_role,
        ).count() == 1

    def test_add_member_reactivates_inactive(self, db, manager_role):
        from tests.factories import UserFactory
        user = UserFactory()
        store = _make_store()
        StoreMembership.objects.create(
            user=user, store=store, role=manager_role, is_active=False,
        )
        m = services.add_member(user, store, manager_role)
        assert m.is_active is True

    def test_remove_member_soft_deactivates(self, db, manager_role):
        from tests.factories import UserFactory
        user = UserFactory()
        store = _make_store()
        services.add_member(user, store, manager_role)
        changed = services.remove_member(user, store, manager_role)
        assert changed is True
        m = StoreMembership.objects.get(user=user, store=store, role=manager_role)
        assert m.is_active is False

    def test_remove_member_returns_false_when_not_member(self, db, manager_role):
        from tests.factories import UserFactory
        user = UserFactory()
        store = _make_store()
        assert services.remove_member(user, store, manager_role) is False

    def test_active_memberships_filters_inactive(self, db, manager_role):
        from tests.factories import UserFactory
        store = _make_store()
        u1 = UserFactory()
        u2 = UserFactory()
        StoreMembership.objects.create(user=u1, store=store, role=manager_role, is_active=True)
        StoreMembership.objects.create(user=u2, store=store, role=manager_role, is_active=False)
        active = list(services.active_memberships(store))
        assert len(active) == 1
        assert active[0].user_id == u1.id


@pytest.mark.django_db
class TestUserHasPermission:
    def test_delegates_to_resolver(self, manager_membership):
        from apps.permissions.resolver import PermissionResolver
        user, store, _ = manager_membership
        # The manager has no explicit grants in this fixture; resolver returns False.
        assert services.user_has_permission(user, store, "orders.view") is False

    def test_superuser_bypass(self, manager_membership):
        from django.contrib.auth import get_user_model
        user, store, _ = manager_membership
        User = get_user_model()
        su = User.objects.create_superuser(email="su@x.com", password="x")
        assert services.user_has_permission(su, store, "anything.at_all") is True


@pytest.mark.django_db
class TestCachedPermissionsDecorator:
    def test_caches_result_and_picks_up_changes(self, db):
        from apps.permissions.cache import cached_permissions

        call_count = {"n": 0}

        @cached_permissions(key_fn=lambda x: f"test:deco:{x}")
        def expensive(x: int) -> int:
            call_count["n"] += 1
            return x * 2

        # First call → computes and caches.
        assert expensive(5) == 10
        assert call_count["n"] == 1
        # Second call → cache hit, no recompute.
        assert expensive(5) == 10
        assert call_count["n"] == 1
        # Different key → recompute.
        assert expensive(7) == 14
        assert call_count["n"] == 2


@pytest.mark.django_db
class TestCacheBumpHelpers:
    def test_bump_user_version_none_safe(self):
        from apps.permissions.cache import bump_user_version
        assert bump_user_version(None) == 0

    def test_bump_store_plan_version_none_safe(self):
        from apps.permissions.cache import bump_store_plan_version
        assert bump_store_plan_version(None) == 0

    def test_bump_user_version_increments(self):
        from apps.permissions.cache import bump_user_version, get_user_version
        # Default is 1.
        assert get_user_version(999) == 1
        v = bump_user_version(999)
        assert v == 2
        assert get_user_version(999) == 2
        # Bump again.
        v = bump_user_version(999)
        assert v == 3

    def test_bump_store_plan_version_increments(self):
        from apps.permissions.cache import (
            bump_store_plan_version,
            get_store_plan_version,
        )
        assert get_store_plan_version(999) == 1
        v = bump_store_plan_version(999)
        assert v == 2
        assert get_store_plan_version(999) == 2

    def test_user_perm_key_format(self):
        from apps.permissions.cache import user_perm_key
        assert user_perm_key(42, 7, 3) == "rbac:user:42:store:7:perms:v3"

    def test_user_feature_key_format(self):
        from apps.permissions.cache import user_feature_key
        assert user_feature_key(42, 7, 3, 5) == (
            "rbac:user:42:store:7:features:v3:p5"
        )

    def test_user_jwt_perms_key_format(self):
        from apps.permissions.cache import user_jwt_perms_key
        assert user_jwt_perms_key(42, 3) == "rbac:user:42:jwt:perms:v3"


@pytest.mark.django_db
class TestContextProcessor:
    def test_rbac_context_includes_user_and_store(self, manager_membership):
        from apps.permissions.context_processors import rbac

        user, store, _ = manager_membership

        class _FakeRequest:
            pass

        req = _FakeRequest()
        req.user = user
        req.store = store
        ctx = rbac(req)
        assert ctx["rbac"]["user"] is user
        assert ctx["rbac"]["store"] is store
        assert ctx["rbac"]["is_authenticated"] is True

    def test_rbac_context_anonymous_user(self):
        from django.contrib.auth.models import AnonymousUser
        from apps.permissions.context_processors import rbac

        class _FakeRequest:
            pass

        req = _FakeRequest()
        req.user = AnonymousUser()
        req.store = None
        ctx = rbac(req)
        assert ctx["rbac"]["is_authenticated"] is False

    def test_rbac_context_no_user_attr(self):
        from apps.permissions.context_processors import rbac

        class _FakeRequest:
            pass

        req = _FakeRequest()
        # No user, no store attributes at all.
        ctx = rbac(req)
        assert ctx["rbac"]["user"] is None
        assert ctx["rbac"]["store"] is None
        assert ctx["rbac"]["is_authenticated"] is False