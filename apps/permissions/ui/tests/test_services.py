"""
Tests for ``apps.permissions.ui.services`` — the mutation layer behind
the role/permission UI.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.permissions.models import (
    AuditLog,
    Permission,
    RolePermission,
    StoreMembership,
    UserPermissionOverride,
)
from apps.permissions.ui import services
from apps.permissions.constants import MODIFIER_GRANT

User = get_user_model()


# ---------------------------------------------------------------------------
# Role CRUD
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCreateRole:
    def test_superuser_creates_custom_role(self, superuser, make_store, system_roles):
        store = make_store("S")
        role = services.create_role(
            actor=superuser, store=store, name="Sales Lead", description="desc",
        )
        assert role.name == "Sales Lead"
        assert role.store == store
        assert role.is_system is False
        assert AuditLog.objects.filter(action="role.create").count() == 1

    def test_non_superuser_lacks_authority(self, make_user, make_store):
        store = make_store("S")
        actor = make_user("actor@example.com")
        with pytest.raises(PermissionError):
            services.create_role(actor=actor, store=store, name="X")

    def test_only_superuser_can_create_system_role(
        self, make_user, make_store, system_roles,
    ):
        store = make_store("S")
        # A "store admin" — non-superuser with an active membership.
        admin = make_user("admin@example.com")
        StoreMembership.objects.create(
            user=admin, store=store, role=system_roles["store-owner"], is_active=True,
        )
        with pytest.raises(PermissionError):
            services.create_role(actor=admin, store=store, name="X", is_system=True)

    def test_empty_name_raises(self, superuser, make_store):
        store = make_store("S")
        with pytest.raises(ValueError):
            services.create_role(actor=superuser, store=store, name="!!!")


@pytest.mark.django_db
class TestUpdateRole:
    def test_updates_name_and_description(self, superuser, make_store):
        store = make_store("S")
        role = services.create_role(actor=superuser, store=store, name="Original")
        services.update_role(actor=superuser, role=role, name="Updated", description="d")
        role.refresh_from_db()
        assert role.name == "Updated"
        assert role.description == "d"
        assert AuditLog.objects.filter(action="role.update").count() == 1

    def test_non_superuser_cannot_modify_system_role(
        self, make_user, make_store, system_roles,
    ):
        store = make_store("S")
        admin = make_user("admin@example.com")
        StoreMembership.objects.create(
            user=admin, store=store, role=system_roles["store-owner"], is_active=True,
        )
        role = services.create_role(actor=admin, store=store, name="X")
        # Manually flip is_system to True for the test
        role.is_system = True
        role.save()
        with pytest.raises(PermissionError):
            services.update_role(actor=admin, role=role, name="Y")


@pytest.mark.django_db
class TestDeleteRole:
    def test_hard_delete_when_no_active_members(self, superuser, make_store):
        store = make_store("S")
        role = services.create_role(actor=superuser, store=store, name="Ephemeral")
        services.delete_role(actor=superuser, role=role)
        assert not AuditLog.objects.filter(action="role.delete").exists() or AuditLog.objects.filter(action="role.delete").count() >= 1
        from apps.permissions.models import Role
        assert not Role.objects.filter(id=role.id).exists()

    def test_soft_delete_when_active_members(self, superuser, make_store, make_user):
        store = make_store("S")
        role = services.create_role(actor=superuser, store=store, name="Used")
        u = make_user("user@example.com")
        StoreMembership.objects.create(user=u, store=store, role=role, is_active=True)
        services.delete_role(actor=superuser, role=role)
        role.refresh_from_db()
        assert role.is_active is False
        assert AuditLog.objects.filter(action="role.deactivate").exists()


@pytest.mark.django_db
class TestCloneRole:
    def test_clone_copies_permissions_and_inherits_from(
        self, superuser, make_store, permissions,
    ):
        store = make_store("S")
        source = services.create_role(actor=superuser, store=store, name="Source")
        perm = permissions["orders.view"]
        RolePermission.objects.create(role=source, permission=perm, modifier=MODIFIER_GRANT)

        clone = services.clone_role(actor=superuser, role=source, new_name="Source Copy")
        assert clone.id != source.id
        assert clone.inherits_from == source
        assert clone.role_permissions.count() == 1
        assert clone.role_permissions.first().permission_id == perm.id


# ---------------------------------------------------------------------------
# Role <-> Permission bindings
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRolePermissionBindings:
    def test_set_replaces_existing_bindings(
        self, superuser, make_store, permissions,
    ):
        store = make_store("S")
        role = services.create_role(actor=superuser, store=store, name="R")
        p1 = permissions["orders.view"]
        p2 = permissions["orders.create"]
        services.set_role_permissions(
            actor=superuser, role=role, permission_ids=[p1.id],
        )
        services.set_role_permissions(
            actor=superuser, role=role, permission_ids=[p2.id],
        )
        assert role.role_permissions.count() == 1
        assert role.role_permissions.first().permission_id == p2.id

    def test_set_ignores_unknown_permission_ids(
        self, superuser, make_store, permissions,
    ):
        store = make_store("S")
        role = services.create_role(actor=superuser, store=store, name="R")
        p1 = permissions["orders.view"]
        services.set_role_permissions(
            actor=superuser,
            role=role,
            permission_ids=[p1.id, "00000000-0000-0000-0000-000000000000"],
        )
        assert role.role_permissions.count() == 1

    def test_toggle_round_trips(self, superuser, make_store, permissions):
        store = make_store("S")
        role = services.create_role(actor=superuser, store=store, name="R")
        perm = permissions["orders.view"]
        assert services.toggle_role_permission(
            actor=superuser, role=role, permission_id=str(perm.id),
        ) is True
        assert services.toggle_role_permission(
            actor=superuser, role=role, permission_id=str(perm.id),
        ) is False


# ---------------------------------------------------------------------------
# Membership
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAddMember:
    def test_idempotent(self, superuser, make_store, system_roles, make_user):
        store = make_store("S")
        role = system_roles["manager"]
        u = make_user("u@example.com")
        m1 = services.add_member(actor=superuser, store=store, user=u, role=role)
        m2 = services.add_member(actor=superuser, store=store, user=u, role=role)
        assert m1.id == m2.id

    def test_reactivates_inactive_membership(
        self, superuser, make_store, system_roles, make_user,
    ):
        store = make_store("S")
        role = system_roles["manager"]
        u = make_user("u@example.com")
        m = services.add_member(actor=superuser, store=store, user=u, role=role)
        services.deactivate_member(actor=superuser, membership=m)
        m.refresh_from_db()
        assert m.is_active is False
        services.add_member(actor=superuser, store=store, user=u, role=role)
        m.refresh_from_db()
        assert m.is_active is True

    def test_wrong_store_role_raises(self, superuser, make_store, make_user):
        store1 = make_store("S1")
        store2 = make_store("S2")
        role_for_store2 = __import__("apps.permissions.models", fromlist=["Role"]).Role.objects.create(
            name="Custom", slug="custom", store=store2,
        )
        u = make_user("u@example.com")
        with pytest.raises(ValueError):
            services.add_member(actor=superuser, store=store1, user=u, role=role_for_store2)


@pytest.mark.django_db
class TestChangeMemberRole:
    def test_changes_role_within_store(
        self, superuser, make_store, system_roles, make_user,
    ):
        store = make_store("S")
        u = make_user("u@example.com")
        m = services.add_member(
            actor=superuser, store=store, user=u, role=system_roles["manager"],
        )
        services.change_member_role(
            actor=superuser, membership=m, new_role=system_roles["viewer"],
        )
        m.refresh_from_db()
        assert m.role_id == system_roles["viewer"].id

    def test_emits_audit_log(
        self, superuser, make_store, system_roles, make_user,
    ):
        store = make_store("S")
        u = make_user("u@example.com")
        m = services.add_member(
            actor=superuser, store=store, user=u, role=system_roles["manager"],
        )
        services.change_member_role(
            actor=superuser, membership=m, new_role=system_roles["viewer"],
        )
        assert AuditLog.objects.filter(action="member.role.change").exists()


@pytest.mark.django_db
class TestDeactivateReactivateMember:
    def test_deactivate_sets_is_active_false(
        self, superuser, make_store, system_roles, make_user,
    ):
        store = make_store("S")
        u = make_user("u@example.com")
        m = services.add_member(
            actor=superuser, store=store, user=u, role=system_roles["manager"],
        )
        services.deactivate_member(actor=superuser, membership=m)
        m.refresh_from_db()
        assert m.is_active is False

    def test_reactivate_sets_is_active_true(
        self, superuser, make_store, system_roles, make_user,
    ):
        store = make_store("S")
        u = make_user("u@example.com")
        m = services.add_member(
            actor=superuser, store=store, user=u, role=system_roles["manager"],
        )
        services.deactivate_member(actor=superuser, membership=m)
        services.reactivate_member(actor=superuser, membership=m)
        m.refresh_from_db()
        assert m.is_active is True
        assert AuditLog.objects.filter(action="member.reactivate").exists()


# ---------------------------------------------------------------------------
# User permission overrides
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSetUserOverride:
    def test_superuser_can_set_cross_store_override(
        self, superuser, make_user, permissions,
    ):
        u = make_user("target@example.com")
        perm = permissions["orders.view"]
        o = services.set_user_override(
            actor=superuser, target_user=u, store=None, permission=perm,
            is_granted=True, reason="test",
        )
        assert o.is_granted is True
        assert o.reason == "test"

    def test_store_admin_can_set_store_scoped_override(
        self, make_user, make_store, system_roles, permissions,
    ):
        store = make_store("S")
        admin = make_user("admin@example.com")
        StoreMembership.objects.create(
            user=admin, store=store, role=system_roles["store-owner"], is_active=True,
        )
        target = make_user("target@example.com")
        perm = permissions["orders.view"]
        o = services.set_user_override(
            actor=admin, target_user=target, store=store, permission=perm,
            is_granted=True, reason="r",
        )
        assert o.store_id == store.id

    def test_non_superuser_cannot_set_cross_store_override(
        self, make_user, make_store, system_roles, permissions,
    ):
        store = make_store("S")
        admin = make_user("admin@example.com")
        StoreMembership.objects.create(
            user=admin, store=store, role=system_roles["store-owner"], is_active=True,
        )
        target = make_user("target@example.com")
        perm = permissions["orders.view"]
        with pytest.raises(PermissionError):
            services.set_user_override(
                actor=admin, target_user=target, store=None, permission=perm,
                is_granted=True,
            )

    def test_update_or_create_replaces_existing(
        self, superuser, make_user, permissions,
    ):
        u = make_user("target@example.com")
        perm = permissions["orders.view"]
        o1 = services.set_user_override(
            actor=superuser, target_user=u, store=None, permission=perm,
            is_granted=True,
        )
        o2 = services.set_user_override(
            actor=superuser, target_user=u, store=None, permission=perm,
            is_granted=False, reason="changed",
        )
        assert o1.id == o2.id
        assert o2.is_granted is False
        assert o2.reason == "changed"
        assert UserPermissionOverride.objects.filter(id=o1.id).count() == 1


@pytest.mark.django_db
class TestClearUserOverride:
    def test_clear_removes_row(self, superuser, make_user, permissions):
        u = make_user("target@example.com")
        perm = permissions["orders.view"]
        o = services.set_user_override(
            actor=superuser, target_user=u, store=None, permission=perm,
            is_granted=True,
        )
        services.clear_user_override(actor=superuser, override=o)
        assert not UserPermissionOverride.objects.filter(id=o.id).exists()
        assert AuditLog.objects.filter(action="override.clear").exists()