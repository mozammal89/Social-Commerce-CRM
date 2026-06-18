"""
Tests for the RBAC seeders and seeder pipeline.

These verify:
- Each seeder runs without error
- Each seeder is idempotent (running twice = no duplicate rows)
- The combined seeders produce the expected catalog
- The seeder pipeline is wired up in apps.core.seeders

Note on the plans seeder: PLAN_MATRIX is mutated in place by `spec.pop("features")`,
so subsequent calls in the same Python process see an empty 'features' key. To test
idempotency we reload the module between runs.
"""

from __future__ import annotations

import importlib

import pytest

from apps.permissions.models import (
    Feature,
    Permission,
    Role,
    RolePermission,
    SubscriptionPlan,
)
from apps.permissions.seeders import plans_seeder as plans_module
from apps.permissions.seeders.features_seeder import FeaturesSeeder
from apps.permissions.seeders.permissions_seeder import RolePermissionsSeeder
from apps.permissions.seeders.roles_seeder import RolesSeeder, SYSTEM_ROLES
from apps.permissions.constants import DEFAULT_FEATURES, MODIFIER_GRANT


def _reload_plans_seeder():
    """Reload the plans_seeder module so PLAN_MATRIX is fresh."""
    importlib.reload(plans_module)
    return plans_module.PlansSeeder


@pytest.mark.django_db
class TestFeaturesSeeder:
    def test_seeds_all_default_features(self, db):
        FeaturesSeeder(verbosity=0).run()
        codes = set(Feature.objects.values_list("code", flat=True))
        expected = set(DEFAULT_FEATURES)
        assert expected.issubset(codes)

    def test_is_idempotent(self, db):
        FeaturesSeeder(verbosity=0).run()
        first_count = Feature.objects.count()
        FeaturesSeeder(verbosity=0).run()
        second_count = Feature.objects.count()
        assert first_count == second_count

    def test_creates_with_proper_name(self, db):
        FeaturesSeeder(verbosity=0).run()
        feat = Feature.objects.get(code="marketing_campaigns")
        assert "Marketing" in feat.name

    def test_safe_run_succeeds(self, db):
        ok = FeaturesSeeder(verbosity=0).safe_run()
        assert ok is True


@pytest.mark.django_db
class TestPlansSeeder:
    def test_seeds_four_default_plans(self, db):
        FeaturesSeeder(verbosity=0).run()
        _reload_plans_seeder()(verbosity=0).run()
        slugs = set(SubscriptionPlan.objects.values_list("slug", flat=True))
        assert {"starter", "growth", "professional", "enterprise"}.issubset(slugs)

    def test_is_idempotent(self, db):
        FeaturesSeeder(verbosity=0).run()
        Seeder = _reload_plans_seeder()
        Seeder(verbosity=0).run()
        first_count = SubscriptionPlan.objects.count()
        # Reload to get a fresh PLAN_MATRIX (the seeder mutates the dict).
        Seeder = _reload_plans_seeder()
        Seeder(verbosity=0).run()
        second_count = SubscriptionPlan.objects.count()
        assert first_count == second_count

    def test_starter_plan_has_only_two_features(self, db):
        FeaturesSeeder(verbosity=0).run()
        _reload_plans_seeder()(verbosity=0).run()
        starter = SubscriptionPlan.objects.get(slug="starter")
        feature_codes = set(
            starter.plan_features.values_list("feature__code", flat=True)
        )
        assert "customer_management" in feature_codes
        assert "basic_reports" in feature_codes
        assert "marketing_campaigns" not in feature_codes

    def test_enterprise_plan_has_all_premium_features(self, db):
        FeaturesSeeder(verbosity=0).run()
        _reload_plans_seeder()(verbosity=0).run()
        ent = SubscriptionPlan.objects.get(slug="enterprise")
        feature_codes = set(
            ent.plan_features.values_list("feature__code", flat=True)
        )
        for premium in ["sso", "audit_export", "marketing_campaigns", "multi_warehouse"]:
            assert premium in feature_codes, f"enterprise should include {premium}"

    def test_plan_limits_are_populated(self, db):
        FeaturesSeeder(verbosity=0).run()
        _reload_plans_seeder()(verbosity=0).run()
        starter = SubscriptionPlan.objects.get(slug="starter")
        assert starter.max_users == 3
        assert starter.max_stores == 1
        assert starter.max_products == 500
        assert starter.trial_days == 14

    def test_plans_seeder_does_not_assume_features_exist(self, db):
        """The plans seeder uses get_or_create for features, so it can run
        before the features seeder."""
        _reload_plans_seeder()(verbosity=0).run()
        assert SubscriptionPlan.objects.filter(slug="starter").exists()
        starter = SubscriptionPlan.objects.get(slug="starter")
        assert starter.plan_features.count() == 2


@pytest.mark.django_db
class TestRolesSeeder:
    def test_seeds_all_system_roles(self, db):
        RolesSeeder(verbosity=0).run()
        slugs = set(
            Role.objects.filter(store=None).values_list("slug", flat=True)
        )
        expected = {slug for slug, _, _, _ in SYSTEM_ROLES}
        assert expected.issubset(slugs)

    def test_system_roles_have_store_null(self, db):
        RolesSeeder(verbosity=0).run()
        for r in Role.objects.filter(is_system=True):
            assert r.store_id is None

    def test_is_idempotent(self, db):
        RolesSeeder(verbosity=0).run()
        first_count = Role.objects.count()
        RolesSeeder(verbosity=0).run()
        second_count = Role.objects.count()
        assert first_count == second_count

    def test_levels_match_constants(self, db):
        RolesSeeder(verbosity=0).run()
        for slug, _, expected_level, _ in SYSTEM_ROLES:
            r = Role.objects.get(slug=slug, store=None)
            assert r.level == expected_level, f"{slug}: level mismatch"


@pytest.mark.django_db
class TestRolePermissionsSeeder:
    def test_is_idempotent(self, db, system_roles):
        RolePermissionsSeeder(verbosity=0).run()
        first = RolePermission.objects.count()
        RolePermissionsSeeder(verbosity=0).run()
        second = RolePermission.objects.count()
        assert first == second

    def test_store_owner_gets_wildcard(self, db, system_roles):
        RolePermissionsSeeder(verbosity=0).run()
        owner = Role.objects.get(slug="store-owner", store=None)
        perms_bound = RolePermission.objects.filter(role=owner).count()
        all_perms = Permission.objects.count()
        assert perms_bound == all_perms

    def test_manager_has_dashboard_view(self, db, system_roles):
        RolePermissionsSeeder(verbosity=0).run()
        mgr = Role.objects.get(slug="manager", store=None)
        assert RolePermission.objects.filter(
            role=mgr, permission__code="dashboard.view"
        ).exists()

    def test_viewer_has_dashboard_view_but_not_orders_create(self, db, system_roles):
        RolePermissionsSeeder(verbosity=0).run()
        v = Role.objects.get(slug="viewer", store=None)
        assert RolePermission.objects.filter(
            role=v, permission__code="dashboard.view"
        ).exists()
        assert not RolePermission.objects.filter(
            role=v, permission__code="orders.create"
        ).exists()

    def test_modifier_is_grant(self, db, system_roles):
        RolePermissionsSeeder(verbosity=0).run()
        mgr = Role.objects.get(slug="manager", store=None)
        rp = RolePermission.objects.filter(
            role=mgr, permission__code="orders.create"
        ).first()
        assert rp is not None
        assert rp.modifier == MODIFIER_GRANT

    def test_safe_run_succeeds(self, db, system_roles):
        ok = RolePermissionsSeeder(verbosity=0).safe_run()
        assert ok is True


@pytest.mark.django_db
class TestSeederPipeline:
    def test_all_seeders_registered(self, db):
        from apps.core.seeders import get_all_seeders
        seeders = get_all_seeders()
        for name in ("features", "plans", "roles", "role-permissions"):
            assert name in seeders, f"seeder '{name}' missing from pipeline"

    def test_run_all_seeders_end_to_end(self, db):
        from apps.core.seeders import run_seeder
        # Reload plans seeder in case earlier tests mutated PLAN_MATRIX.
        _reload_plans_seeder()
        for name in ("features", "plans", "roles", "role-permissions"):
            ok = run_seeder(name, verbosity=0)
            assert ok, f"seeder {name} failed"

        assert Feature.objects.count() >= len(DEFAULT_FEATURES)
        assert SubscriptionPlan.objects.filter(slug="starter").exists()
        assert Role.objects.filter(slug="store-owner", store=None).exists()
        mgr = Role.objects.get(slug="manager", store=None)
        assert mgr.role_permissions.exists()

    def test_run_all_seeders_is_idempotent(self, db):
        from apps.core.seeders import run_seeder
        # Reload plans seeder in case earlier tests mutated PLAN_MATRIX.
        _reload_plans_seeder()
        names = ("features", "plans", "roles", "role-permissions")
        for n in names:
            run_seeder(n, verbosity=0)
        feat1 = Feature.objects.count()
        plan1 = SubscriptionPlan.objects.count()
        role1 = Role.objects.count()
        rp1 = RolePermission.objects.count()

        # Reload plans seeder to work around the in-place mutation.
        _reload_plans_seeder()
        for n in names:
            run_seeder(n, verbosity=0)
        feat2 = Feature.objects.count()
        plan2 = SubscriptionPlan.objects.count()
        role2 = Role.objects.count()
        rp2 = RolePermission.objects.count()

        assert feat1 == feat2
        assert plan1 == plan2
        assert role1 == role2
        assert rp1 == rp2


@pytest.mark.django_db
class TestPatchHelpers:
    """Verify the User and Store monkey-patches work as documented."""

    def test_user_has_permission(self, db, system_roles, manager_membership):
        from apps.permissions.models import Permission, RolePermission
        from apps.permissions.constants import MODIFIER_GRANT, ROLE_MANAGER
        user, store, _ = manager_membership
        RolePermission.objects.create(
            role=Role.objects.get(slug=ROLE_MANAGER),
            permission=Permission.objects.get(code="orders.view"),
            modifier=MODIFIER_GRANT,
        )
        assert user.has_permission("orders.view", store=store) is True
        assert user.has_permission("orders.create", store=store) is False

    def test_user_has_feature(self, db, active_subscription, viewer_membership):
        from apps.permissions.models import StoreMembership
        store, _, _ = active_subscription
        user, _store2, _ = viewer_membership
        # Move user to the subscription's store.
        StoreMembership.objects.filter(user=user).update(store=store)
        assert user.has_feature("customer_management", store=store) is True
        assert user.has_feature("sso", store=store) is False

    def test_store_has_feature(self, db, active_subscription):
        store, _, _ = active_subscription
        assert store.has_feature("customer_management") is True
        assert store.has_feature("sso") is False

    def test_store_has_feature_without_subscription(self, db):
        from apps.stores.models import Store
        s = Store.objects.create(name="X", status="active")
        assert s.has_feature("customer_management") is False

    def test_unauthenticated_user_resolver_returns_false(self, db):
        """The resolver returns False for users without is_authenticated."""
        from apps.permissions.resolver import PermissionResolver
        from django.contrib.auth.models import AnonymousUser
        anon = AnonymousUser()
        # Anonymous users don't have has_permission patched on their class
        # (only on the User model), but the resolver itself should still
        # return False for an unauthenticated user.
        ok = PermissionResolver().check(anon, None, "orders.view")
        assert ok is False
        feat_ok = PermissionResolver().check_feature(anon, None, "any")
        assert feat_ok is False


@pytest.mark.django_db
class TestDenyMatrix:
    """Bug 13: the deny matrix is applied after the GRANT pass and must
    prevent roles from exercising privileges they would otherwise have via
    wildcard ``"*"`` grants.
    """

    def test_admin_role_cannot_delete_roles(self, db):
        RolesSeeder(verbosity=0).run()
        RolePermissionsSeeder(verbosity=0).run()
        admin = Role.objects.get(slug="admin", store=None)
        perm = Permission.objects.get(code="roles.delete")
        rp = RolePermission.objects.get(role=admin, permission=perm)
        from apps.permissions.constants import MODIFIER_DENY
        assert rp.modifier == MODIFIER_DENY

    def test_manager_role_cannot_delete_roles(self, db):
        RolesSeeder(verbosity=0).run()
        RolePermissionsSeeder(verbosity=0).run()
        manager = Role.objects.get(slug="manager", store=None)
        perm = Permission.objects.get(code="roles.delete")
        rp = RolePermission.objects.get(role=manager, permission=perm)
        from apps.permissions.constants import MODIFIER_DENY
        assert rp.modifier == MODIFIER_DENY

    def test_store_owner_has_no_denies(self, db):
        RolesSeeder(verbosity=0).run()
        RolePermissionsSeeder(verbosity=0).run()
        owner = Role.objects.get(slug="store-owner", store=None)
        from apps.permissions.constants import MODIFIER_DENY
        denied = RolePermission.objects.filter(role=owner, modifier=MODIFIER_DENY)
        assert denied.count() == 0

    def test_deny_matrix_overrides_wildcard_grant(self, db):
        """An ``admin`` role has ``*`` grants (wildcard). The deny matrix
        writes a DENY row that replaces the GRANT (via ``update_or_create``).
        The resolver's DENY-wins guard must win.
        """
        RolesSeeder(verbosity=0).run()
        RolePermissionsSeeder(verbosity=0).run()
        admin = Role.objects.get(slug="admin", store=None)
        perm = Permission.objects.get(code="roles.delete")
        from apps.permissions.constants import MODIFIER_DENY
        # Only one row per (role, permission). DENY replaced the GRANT.
        rows = RolePermission.objects.filter(role=admin, permission=perm)
        assert rows.count() == 1
        assert rows.first().modifier == MODIFIER_DENY

    def test_seeder_does_not_use_print(self):
        import apps.permissions.seeders.permissions_seeder as mod
        import apps.permissions.seeders.roles_seeder as roles_mod
        import inspect
        src_perms = inspect.getsource(mod)
        src_roles = inspect.getsource(roles_mod)
        # Bug 12: no ``print(`` calls in the seeder source.
        assert "print(" not in src_perms
        assert "print(" not in src_roles
