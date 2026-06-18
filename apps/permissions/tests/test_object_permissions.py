"""Tests for object-level authorization checkers."""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from apps.permissions import object_permissions
from apps.permissions.object_permissions import (
    clear_checkers,
    customer_object_checker,
    get_object_checker,
    list_registered,
    order_object_checker,
    register_checker,
)


class TestCheckerRegistry:
    def test_register_and_get_checker(self):
        clear_checkers()

        @register_checker("test_resource")
        def my_checker(user, store, code, obj):
            return True

        assert get_object_checker("test_resource") is my_checker
        assert "test_resource" in list_registered()
        clear_checkers()


@pytest.mark.django_db
class TestBuiltInCheckers:
    def setup_method(self):
        clear_checkers()
        # Re-register the built-in checkers (clear_checkers() emptied them).
        from apps.permissions import object_permissions as op
        op._checkers["orders"] = order_object_checker
        op._checkers["customers"] = customer_object_checker

    def teardown_method(self):
        clear_checkers()
        from apps.permissions import object_permissions as op
        op._checkers["orders"] = order_object_checker
        op._checkers["customers"] = customer_object_checker

    def test_order_checker_with_no_user_returns_false(self):
        order = SimpleNamespace(assignees=None, store=None)
        assert order_object_checker(None, None, "orders.view", order) is False

    def test_order_checker_passthrough_when_no_assignees_relation(
        self, db, system_roles,
    ):
        from tests.factories import UserFactory
        from apps.stores.models import Store
        s = Store.objects.create(name="X", status="active")
        u = UserFactory()
        order = SimpleNamespace(assignees=None, store=s)
        assert order_object_checker(u, s, "orders.view", order) is False

    def test_order_checker_manager_level_passes(
        self, db, system_roles, manager_membership,
    ):
        user, store, _ = manager_membership
        # Manager has level 60 → passes without assignees.
        order = SimpleNamespace(assignees=None, store=store)
        assert order_object_checker(user, store, "orders.view", order) is True

    def test_resolver_uses_object_checker(self, db, system_roles, manager_membership):
        from apps.permissions.models import Permission, RolePermission
        from apps.permissions.constants import MODIFIER_GRANT, ROLE_MANAGER
        from apps.permissions.resolver import PermissionResolver
        from apps.permissions import object_permissions as op

        user, store, _ = manager_membership
        perm = Permission.objects.get(code="orders.view")
        RolePermission.objects.create(
            role=__import__("apps.permissions.models", fromlist=["Role"]).Role.objects.get(slug=ROLE_MANAGER),
            permission=perm, modifier=MODIFIER_GRANT,
        )
        # Build a fake order with no assignees — manager-level user passes.
        order = SimpleNamespace(assignees=None, store=store)
        result = PermissionResolver().check(user, store, "orders.view", obj=order)
        assert result is True
