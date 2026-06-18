"""Tests for the resource registry and sync_permissions command."""

from __future__ import annotations

import pytest

from apps.permissions.models import Permission, Resource
from apps.permissions.registry import (
    ACTIONS,
    RESOURCES,
    iter_permissions,
    is_valid_permission_code,
    split_code,
)


@pytest.mark.django_db
class TestRegistry:
    def test_actions_constant_contains_required_verbs(self):
        for verb in ("view", "create", "update", "delete", "export",
                     "import", "approve", "assign", "manage"):
            assert verb in ACTIONS

    def test_resources_dict_has_all_required_resources(self):
        for code in (
            "dashboard", "customers", "products", "orders", "reports",
            "warehouses", "campaigns", "employees", "roles", "settings",
        ):
            assert code in RESOURCES

    def test_iter_permissions_yields_resource_action_pairs(self):
        perms = iter_permissions()
        assert len(perms) > 0
        for p in perms:
            assert p["code"] == f"{p['resource']}.{p['action']}"
            assert p["action"] in p["code"]

    def test_is_valid_permission_code_accepts_known(self):
        assert is_valid_permission_code("orders.create")
        assert is_valid_permission_code("customers.view")

    def test_is_valid_permission_code_rejects_unknown(self):
        assert not is_valid_permission_code("orders.nuke")
        assert not is_valid_permission_code("unknown.view")
        assert not is_valid_permission_code("nodot")
        assert not is_valid_permission_code("")

    def test_split_code(self):
        assert split_code("orders.create") == ("orders", "create")
        assert split_code("customers") is None


@pytest.mark.django_db
class TestSyncPermissionsCommand:
    def test_creates_resources_and_permissions(self, resources, permissions):
        assert Resource.objects.count() == len(RESOURCES)
        # Each resource × actions should yield at least one Permission row.
        expected_count = sum(len(spec["actions"]) for spec in RESOURCES.values())
        assert Permission.objects.count() == expected_count

    def test_sync_permissions_is_idempotent(self):
        from django.core.management import call_command

        # First call was done by autouse fixture. Run again — counts must not change.
        call_command("sync_permissions", verbosity=0)
        first = Permission.objects.count()
        call_command("sync_permissions", verbosity=0)
        second = Permission.objects.count()
        assert first == second
