"""
Tests for the role/permission management UI service layer.

Run with:
    pytest apps/permissions/ui/tests/ -v
or:
    python manage.py test apps.permissions.ui
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import TestCase

from apps.permissions.models import (
    AuditLog,
    Permission,
    Role,
    RolePermission,
    StoreMembership,
)
from apps.permissions.ui import services
from apps.stores.models import Store

User = get_user_model()


class RoleCRUDTests(TestCase):
    """Cover the basic CRUD operations on Role."""

    def setUp(self):
        self.superuser = User.objects.create_superuser(email="su@x.com", password="pw")
        self.store = Store.objects.create(name="S", slug="s")

    def test_create_custom_role_logs_audit(self):
        role = services.create_role(
            actor=self.superuser,
            store=self.store,
            name="Sales Lead",
            description="Leads the sales team",
            level=60,
        )
        self.assertEqual(role.name, "Sales Lead")
        self.assertEqual(role.store, self.store)
        self.assertFalse(role.is_system)
        self.assertEqual(AuditLog.objects.filter(action="role.create").count(), 1)

    def test_create_role_requires_authority(self):
        actor = User.objects.create_user(email="u@x.com", password="pw")
        with self.assertRaises(PermissionError):
            services.create_role(actor=actor, store=self.store, name="X")

    def test_only_superuser_can_create_system_role(self):
        store_admin = User.objects.create_user(email="a@x.com", password="pw")
        StoreMembership.objects.create(
            user=store_admin,
            store=self.store,
            role=Role.objects.create(name="Owner", slug="owner", level=100),
        )
        with self.assertRaises(PermissionError):
            services.create_role(
                actor=store_admin, store=self.store, name="System-like", is_system=True,
            )

    def test_delete_role_soft_deactivates_when_active_members(self):
        role = services.create_role(actor=self.superuser, store=self.store, name="Manager")
        u = User.objects.create_user(email="m@x.com", password="pw")
        StoreMembership.objects.create(user=u, store=self.store, role=role, is_active=True)
        services.delete_role(actor=self.superuser, role=role)
        role.refresh_from_db()
        self.assertFalse(role.is_active)
        self.assertTrue(AuditLog.objects.filter(action="role.deactivate").exists())

    def test_clone_role_copies_permissions(self):
        source = services.create_role(actor=self.superuser, store=self.store, name="Source")
        perm = Permission.objects.first()
        services.set_role_permissions(
            actor=self.superuser, role=source, permission_ids=[perm.id],
        )
        clone = services.clone_role(
            actor=self.superuser, role=source, new_name="Source Copy",
        )
        self.assertNotEqual(clone.id, source.id)
        self.assertEqual(clone.inherits_from, source)
        self.assertEqual(clone.role_permissions.count(), 1)


class RolePermissionTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(email="su@x.com", password="pw")
        self.store = Store.objects.create(name="S", slug="s")

    def test_set_role_permissions_replaces_existing(self):
        role = services.create_role(actor=self.superuser, store=self.store, name="R")
        perms = list(Permission.objects.all()[:2])
        services.set_role_permissions(actor=self.superuser, role=role, permission_ids=[perms[0].id])
        services.set_role_permissions(actor=self.superuser, role=role, permission_ids=[perms[1].id])
        self.assertEqual(role.role_permissions.count(), 1)
        self.assertEqual(role.role_permissions.first().permission_id, perms[1].id)

    def test_toggle_permission_round_trips(self):
        role = services.create_role(actor=self.superuser, store=self.store, name="R")
        perm = Permission.objects.first()
        self.assertTrue(services.toggle_role_permission(
            actor=self.superuser, role=role, permission_id=str(perm.id),
        ))
        self.assertFalse(services.toggle_role_permission(
            actor=self.superuser, role=role, permission_id=str(perm.id),
        ))


class MembershipTests(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(email="su@x.com", password="pw")
        self.store = Store.objects.create(name="S", slug="s")
        self.role = Role.objects.create(name="Staff", slug="staff", is_system=True)

    def test_add_member_is_idempotent(self):
        u = User.objects.create_user(email="u@x.com", password="pw")
        m1 = services.add_member(actor=self.superuser, store=self.store, user=u, role=self.role)
        m2 = services.add_member(actor=self.superuser, store=self.store, user=u, role=self.role)
        self.assertEqual(m1.id, m2.id)

    def test_change_member_role(self):
        u = User.objects.create_user(email="u@x.com", password="pw")
        m = services.add_member(actor=self.superuser, store=self.store, user=u, role=self.role)
        new_role = Role.objects.create(name="Manager", slug="mgr")
        services.change_member_role(actor=self.superuser, membership=m, new_role=new_role)
        m.refresh_from_db()
        self.assertEqual(m.role, new_role)

    def test_deactivate_member(self):
        u = User.objects.create_user(email="u@x.com", password="pw")
        m = services.add_member(actor=self.superuser, store=self.store, user=u, role=self.role)
        services.deactivate_member(actor=self.superuser, membership=m)
        m.refresh_from_db()
        self.assertFalse(m.is_active)
