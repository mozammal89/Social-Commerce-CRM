"""
Tests for the legacy M2M → StoreMembership data migration.

These tests use Django's migration executor to apply all migrations
up to and including ``0002_migrate_legacy_memberships``, populate the
legacy M2M tables, and then verify that the forward migration correctly
copied them into StoreMembership rows.

We test in three modes:
  1. Forward migration with existing legacy rows produces StoreMembership rows.
  2. Forward migration is idempotent (running it twice produces no duplicates).
  3. Reverse migration deletes the migrated StoreMembership rows.
"""

from __future__ import annotations

import pytest
from django.apps import apps as django_apps
from django.db import connection

# Import the migration module by file name (Django doesn't expose it as
# a normal Python module because of the numeric prefix).
import importlib
migration_module = importlib.import_module(
    "apps.permissions.migrations.0002_migrate_legacy_memberships"
)
forward = migration_module.forward
backward = migration_module.backward


def _executor():
    from django.db.migrations.executor import MigrationExecutor
    return MigrationExecutor(connection)


def _apply_all():
    """Apply all migrations to the current state."""
    executor = _executor()
    targets = executor.loader.graph.leaf_nodes()
    executor.migrate(targets)


@pytest.mark.django_db(transaction=True)
class TestLegacyMigrationForward:
    def test_owners_become_store_owner_membership(self, db):
        _apply_all()
        from apps.stores.models import Store
        from apps.permissions.models import StoreMembership
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        from tests.factories import UserFactory

        RolesSeeder(verbosity=0).run()
        store = Store.objects.create(name="Legacy 1", status="active")
        user = UserFactory()
        store.owners.add(user)

        forward(django_apps, connection.schema_editor())

        sm_count = StoreMembership.objects.filter(
            user=user, store=store, role__slug="store-owner"
        ).count()
        assert sm_count == 1

    def test_managers_become_manager_membership(self, db):
        _apply_all()
        from apps.stores.models import Store
        from apps.permissions.models import StoreMembership
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        from tests.factories import UserFactory

        RolesSeeder(verbosity=0).run()
        store = Store.objects.create(name="Legacy 2", status="active")
        user = UserFactory()
        store.managers.add(user)

        forward(django_apps, connection.schema_editor())

        sm_count = StoreMembership.objects.filter(
            user=user, store=store, role__slug="manager"
        ).count()
        assert sm_count == 1

    def test_staff_m2m_is_skipped_when_no_staff_role_seeded(self, db):
        """The legacy 'staff' M2M maps to a 'staff' system role. If that
        role hasn't been seeded yet, the migration silently skips — the
        operator can run seeders and re-migrate."""
        _apply_all()
        from apps.stores.models import Store
        from apps.permissions.models import StoreMembership
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        from tests.factories import UserFactory

        RolesSeeder(verbosity=0).run()
        store = Store.objects.create(name="Legacy 3", status="active")
        user = UserFactory()
        store.staff.add(user)

        forward(django_apps, connection.schema_editor())

        # No 'staff' role exists in the seeder, so no membership is created.
        # This documents the migration's skip behavior.
        assert StoreMembership.objects.filter(
            user=user, store=store, role__slug="staff"
        ).count() == 0

    def test_staff_membership_when_staff_role_seeded(self, db):
        """If an operator creates a 'staff' system role, the migration
        will use it."""
        _apply_all()
        from apps.stores.models import Store
        from apps.permissions.models import Role, StoreMembership
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        from tests.factories import UserFactory

        RolesSeeder(verbosity=0).run()
        # Manually create a 'staff' system role for this test.
        Role.objects.create(
            name="Staff", slug="staff", store=None,
            is_system=True, is_active=True, level=10,
        )

        store = Store.objects.create(name="Legacy Staff", status="active")
        user = UserFactory()
        store.staff.add(user)

        forward(django_apps, connection.schema_editor())

        assert StoreMembership.objects.filter(
            user=user, store=store, role__slug="staff"
        ).count() == 1


@pytest.mark.django_db(transaction=True)
class TestLegacyMigrationIdempotency:
    def test_running_forward_twice_does_not_duplicate(self, db):
        _apply_all()
        from apps.stores.models import Store
        from apps.permissions.models import StoreMembership
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        from tests.factories import UserFactory

        RolesSeeder(verbosity=0).run()
        store = Store.objects.create(name="Idem Store", status="active")
        user = UserFactory()
        store.owners.add(user)
        store.managers.add(user)
        # Note: staff M2M has no system role by default, so it's skipped.

        forward(django_apps, connection.schema_editor())
        forward(django_apps, connection.schema_editor())

        # Two memberships: store-owner + manager. staff is skipped.
        assert StoreMembership.objects.filter(user=user, store=store).count() == 2

    def test_running_forward_without_seeded_roles_skips(self, db):
        """If system roles don't exist (seeders not run), the migration
        silently does nothing — the operator can run seeders and re-migrate."""
        _apply_all()
        from apps.stores.models import Store
        from apps.permissions.models import StoreMembership, Role
        from tests.factories import UserFactory

        # Ensure no system roles exist.
        Role.objects.filter(store=None).delete()

        store = Store.objects.create(name="No Roles Store", status="active")
        user = UserFactory()
        store.owners.add(user)

        forward(django_apps, connection.schema_editor())

        assert StoreMembership.objects.filter(user=user, store=store).count() == 0


@pytest.mark.django_db(transaction=True)
class TestLegacyMigrationBackward:
    def test_reverse_removes_migrated_memberships(self, db):
        _apply_all()
        from apps.stores.models import Store
        from apps.permissions.models import StoreMembership
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        from tests.factories import UserFactory

        RolesSeeder(verbosity=0).run()
        store = Store.objects.create(name="Reverse Store", status="active")
        user = UserFactory()
        store.owners.add(user)
        store.managers.add(user)

        forward(django_apps, connection.schema_editor())
        assert StoreMembership.objects.filter(user=user, store=store).count() == 2

        backward(django_apps, connection.schema_editor())
        assert StoreMembership.objects.filter(user=user, store=store).count() == 0

    def test_reverse_leaves_custom_memberships_alone(self, db):
        """Reverse should only remove memberships bound to the legacy
        role slugs; custom roles should remain untouched."""
        _apply_all()
        from apps.stores.models import Store
        from apps.permissions.models import Role, StoreMembership
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        from tests.factories import UserFactory

        RolesSeeder(verbosity=0).run()
        store = Store.objects.create(name="Mixed Store", status="active")
        user = UserFactory()

        # Custom role (per-store).
        custom_role = Role.objects.create(
            name="Refund Approver", slug="refund-approver",
            store=store, is_system=False,
        )
        StoreMembership.objects.create(
            user=user, store=store, role=custom_role, is_active=True,
        )
        store.owners.add(user)

        forward(django_apps, connection.schema_editor())
        assert StoreMembership.objects.filter(user=user, store=store).count() == 2

        backward(django_apps, connection.schema_editor())
        assert StoreMembership.objects.filter(user=user, store=store).count() == 1
        assert StoreMembership.objects.filter(
            user=user, store=store, role=custom_role,
        ).exists()


@pytest.mark.django_db(transaction=True)
class TestLegacyMigrationExecutor:
    """Integration test: actually run the full migration chain."""

    def test_full_migrate_applies_0002(self, db):
        from django.db.migrations.recorder import MigrationRecorder

        applied = MigrationRecorder(connection).applied_migrations()
        assert ("permissions", "0001_initial") in applied

        _apply_all()

        applied = MigrationRecorder(connection).applied_migrations()
        assert ("permissions", "0002_migrate_legacy_memberships") in applied
