"""Tests for the permission resolver."""

from __future__ import annotations

import pytest

from apps.permissions.constants import (
    MODIFIER_DENY,
    MODIFIER_GRANT,
    ROLE_MANAGER,
    ROLE_VIEWER,
)
from apps.permissions.models import (
    Permission,
    Role,
    RolePermission,
    UserPermissionOverride,
)
from apps.permissions.resolver import PermissionResolver


@pytest.mark.django_db
class TestPermissionResolver:
    def test_unauthenticated_user_returns_false(self, resources):
        from django.contrib.auth.models import AnonymousUser
        result = PermissionResolver().check(AnonymousUser(), None, "orders.create")
        assert result is False

    def test_user_without_membership_returns_false(
        self, db, system_roles,
    ):
        # User has NO membership in this store.
        from tests.factories import UserFactory
        from apps.stores.models import Store
        u = UserFactory()
        s = Store.objects.create(name="X", status="active")
        result = PermissionResolver().check(u, s, "orders.create")
        assert result is False

    def test_granted_permission_returns_true(
        self, db, system_roles, manager_membership,
    ):
        user, store, _ = manager_membership
        # Grant 'orders.create' to manager role directly via a custom binding.
        perm = Permission.objects.get(code="orders.create")
        RolePermission.objects.create(
            role=Role.objects.get(slug=ROLE_MANAGER),
            permission=perm,
            modifier=MODIFIER_GRANT,
        )
        result = PermissionResolver().check(user, store, "orders.create")
        assert result is True

    def test_deny_beats_grant(self, db, system_roles):
        """If a user has two roles and one denies, DENY wins."""
        from tests.factories import UserFactory
        from apps.stores.models import Store
        from apps.permissions.models import StoreMembership

        u = UserFactory()
        s = Store.objects.create(name="X", status="active")

        manager = Role.objects.get(slug=ROLE_MANAGER)
        viewer = Role.objects.get(slug=ROLE_VIEWER)
        StoreMembership.objects.create(user=u, store=s, role=manager, is_active=True)
        StoreMembership.objects.create(user=u, store=s, role=viewer, is_active=True)

        perm = Permission.objects.get(code="orders.approve")
        RolePermission.objects.create(role=manager, permission=perm, modifier=MODIFIER_GRANT)
        RolePermission.objects.create(role=viewer, permission=perm, modifier=MODIFIER_DENY)

        # Manager would grant it, viewer denies it → DENY wins → False.
        result = PermissionResolver().check(u, s, "orders.approve")
        assert result is False

    def test_user_override_grant(self, db, system_roles, viewer_membership):
        user, store, _ = viewer_membership
        # Viewer doesn't have orders.create by default; give it via override.
        perm = Permission.objects.get(code="orders.create")
        UserPermissionOverride.objects.create(
            user=user, store=store, permission=perm, is_granted=True,
        )
        assert PermissionResolver().check(user, store, "orders.create") is True

    def test_user_override_deny_is_absolute(self, db, system_roles, manager_membership):
        user, store, _ = manager_membership
        # Manager normally has orders.create via the matrix. Override denies it.
        perm = Permission.objects.get(code="orders.create")
        UserPermissionOverride.objects.create(
            user=user, store=store, permission=perm, is_granted=False,
        )
        assert PermissionResolver().check(user, store, "orders.create") is False

    def test_invalid_code_returns_false(self, owner_membership):
        user, store, _ = owner_membership
        assert PermissionResolver().check(user, store, "orders.nuke") is False
        assert PermissionResolver().check(user, store, "") is False
        assert PermissionResolver().check(user, store, "unknown.view") is False

    def test_superuser_bypasses(self, db, resources):
        from tests.factories import AdminUserFactory
        admin = AdminUserFactory()
        result = PermissionResolver().check(admin, None, "orders.create")
        assert result is True

    def test_cache_returns_consistent_results(
        self, db, system_roles, manager_membership,
    ):
        user, store, _ = manager_membership
        perm = Permission.objects.get(code="orders.create")
        RolePermission.objects.create(
            role=Role.objects.get(slug=ROLE_MANAGER),
            permission=perm, modifier=MODIFIER_GRANT,
        )
        r = PermissionResolver()
        assert r.check(user, store, "orders.create") is True
        # Second call: should hit the cache; result unchanged.
        assert r.check(user, store, "orders.create") is True
