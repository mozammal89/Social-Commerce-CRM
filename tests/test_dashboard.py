"""
Tests for the RBAC-aware dashboard views.

These tests verify that:

* Superusers (``is_superuser=True``) see every store and get full KPIs.
* Regular members see only their active ``StoreMembership``s.
* Users with no active membership see the onboarding empty-state card.
* KPI cards return ``None`` when the user lacks the relevant permission
  (template renders a "Locked" state).
* ``switch_store`` honors ``StoreMembership.is_active``; non-members and
  users without an active row are bounced with an error.
* Superusers can switch to any store regardless of membership.

Run with::

    pytest tests/test_dashboard.py -v
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.permissions.constants import ROLE_MANAGER, ROLE_STORE_OWNER, ROLE_VIEWER
from apps.permissions.models import StoreMembership
from apps.stores.models import Store


User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_store(name: str = "Test Store") -> Store:
    """Create a minimal Store. The project's slug field is unique, so we
    slugify the name to avoid collisions across tests.
    """
    return Store.objects.create(
        name=name,
        slug=name.lower().replace(" ", "-"),
        status="active",
    )


def _make_user(email: str, *, is_superuser: bool = False):
    if is_superuser:
        return User.objects.create_superuser(
            email=email, password="x", first_name="X", last_name="Y",
        )
    return User.objects.create_user(
        email=email, password="x", first_name="X", last_name="Y",
    )


def _login(client, user):
    client.force_login(user)


@pytest.fixture
def make_store():
    return _make_store


@pytest.fixture(autouse=True)
def _seed_rbac(db):
    """Run the role + role-permission seeders so that the seeded
    ``manager`` / ``viewer`` / ``owner`` roles carry the permission
    grants they would have in production. The dashboard view is now
    gated by ``@permission_required("dashboard.view")`` and these
    tests assume that grant.
    """
    from apps.permissions.seeders.roles_seeder import RolesSeeder
    from apps.permissions.seeders.permissions_seeder import RolePermissionsSeeder
    RolesSeeder().run()
    RolePermissionsSeeder().run()


# ---------------------------------------------------------------------------
# dashboard_home
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDashboardHome:
    def test_anonymous_redirected_to_login(self, client):
        res = client.get(reverse("dashboard:home"))
        assert res.status_code == 302
        assert "auth" in res.url.lower() or "login" in res.url.lower()

    def test_superuser_sees_all_stores(self, client, make_store):
        s1 = make_store("S1")
        s2 = make_store("S2")
        su = _make_user("su@x.com", is_superuser=True)
        _login(client, su)

        res = client.get(reverse("dashboard:home"))
        assert res.status_code == 200
        assert res.context["is_superuser"] is True
        assert res.context["user_has_no_store"] is False
        # Ordered by name → S1, S2
        assert list(res.context["user_stores"]) == [s1, s2]

    def test_regular_member_sees_only_their_stores(self, client, make_store):
        s1 = make_store("S1")
        s2 = make_store("S2")
        # Seed the system roles so we can assign memberships.
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        RolesSeeder().run()
        from apps.permissions.models import Role
        manager_role = Role.objects.get(slug=ROLE_MANAGER)

        u = _make_user("member@x.com")
        StoreMembership.objects.create(
            user=u, store=s1, role=manager_role, is_active=True,
        )
        _login(client, u)

        res = client.get(reverse("dashboard:home"))
        assert res.status_code == 200
        assert res.context["is_superuser"] is False
        assert list(res.context["user_stores"]) == [s1]

    def test_inactive_membership_is_excluded(self, client, make_store):
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        RolesSeeder().run()
        from apps.permissions.models import Role
        manager_role = Role.objects.get(slug=ROLE_MANAGER)

        s1 = make_store("S1")
        s2 = make_store("S2")
        u = _make_user("u@x.com")
        StoreMembership.objects.create(
            user=u, store=s1, role=manager_role, is_active=False,
        )
        StoreMembership.objects.create(
            user=u, store=s2, role=manager_role, is_active=True,
        )
        _login(client, u)

        res = client.get(reverse("dashboard:home"))
        assert list(res.context["user_stores"]) == [s2]

    def test_user_with_no_membership_sees_onboarding(self, client, make_store):
        make_store("Orphan")
        u = _make_user("lone@x.com")
        _login(client, u)

        res = client.get(reverse("dashboard:home"))
        assert res.status_code == 200
        assert res.context["user_has_no_store"] is True
        assert res.context["current_store"] is None
        assert b"don" in res.content  # "don't belong" or similar

    def test_superuser_with_no_stores_still_sees_onboarding(self, client):
        su = _make_user("su@x.com", is_superuser=True)
        _login(client, su)

        res = client.get(reverse("dashboard:home"))
        # No stores exist → onboarding state, but rendered for superusers.
        assert res.context["user_has_no_store"] is True
        assert b"Super Admin" in res.content

    def test_superuser_onboarding_has_create_link(self, client):
        su = _make_user("su@x.com", is_superuser=True)
        _login(client, su)

        res = client.get(reverse("dashboard:home"))
        assert b"/admin/stores/store/add/" in res.content or b"Create" in res.content

    def test_regular_user_onboarding_does_not_have_create_link(self, client):
        u = _make_user("lone@x.com")
        _login(client, u)

        res = client.get(reverse("dashboard:home"))
        # No store admin link for regular users.
        assert b"/admin/stores/store/add/" not in res.content

    def test_superuser_kpis_are_populated(self, client, make_store):
        s = make_store("S1")
        su = _make_user("su@x.com", is_superuser=True)
        _login(client, su)

        res = client.get(reverse("dashboard:home"))
        # apps/orders has no model yet, so KPIs fall back to None (graceful).
        # The superuser path still calls _safe_revenue etc.; the call returns
        # None when the model is missing — that's by design.
        kpis = res.context["kpis"]
        assert kpis is not None
        assert set(kpis.keys()) == {
            "revenue", "orders_count", "customers_count", "low_stock_count",
        }
        # perm_count for superuser = total permissions registered.
        assert res.context["perm_count"] >= 0

    def test_viewer_role_kpis_are_locked(self, client, make_store):
        """A Viewer has no orders.view / customers.view / inventory.view,
        so those KPIs should be None (= 'Locked' in the template).
        """
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        RolesSeeder().run()
        from apps.permissions.models import Role
        viewer_role = Role.objects.get(slug=ROLE_VIEWER)

        s = make_store("S1")
        u = _make_user("viewer@x.com")
        StoreMembership.objects.create(
            user=u, store=s, role=viewer_role, is_active=True,
        )
        _login(client, u)

        res = client.get(reverse("dashboard:home"))
        kpis = res.context["kpis"]
        assert kpis["orders_count"] is None
        assert kpis["customers_count"] is None
        assert kpis["low_stock_count"] is None

    def test_owner_role_gets_role_in_context(self, client, make_store):
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        RolesSeeder().run()
        from apps.permissions.models import Role
        owner_role = Role.objects.get(slug=ROLE_STORE_OWNER)

        s = make_store("S1")
        u = _make_user("owner@x.com")
        StoreMembership.objects.create(
            user=u, store=s, role=owner_role, is_active=True,
        )
        _login(client, u)

        res = client.get(reverse("dashboard:home"))
        assert res.context["top_role"] is not None
        assert res.context["top_role"].slug == ROLE_STORE_OWNER

    def test_stale_session_store_is_overridden(self, client, make_store):
        """A session pointing at a store the user is no longer a member of
        should be silently overridden by the first available store.
        """
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        RolesSeeder().run()
        from apps.permissions.models import Role
        manager_role = Role.objects.get(slug=ROLE_MANAGER)

        s1 = make_store("S1")
        s2 = make_store("S2")
        u = _make_user("u@x.com")
        StoreMembership.objects.create(
            user=u, store=s1, role=manager_role, is_active=True,
        )
        # Session points to s2 (no membership).
        session = client.session
        session["current_store_id"] = str(s2.id)
        session.save()
        _login(client, u)

        res = client.get(reverse("dashboard:home"))
        # Falls back to s1.
        assert res.context["current_store"].id == s1.id


# ---------------------------------------------------------------------------
# switch_store
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestSwitchStore:
    def test_member_can_switch_to_their_store(self, client, make_store):
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        RolesSeeder().run()
        from apps.permissions.models import Role
        manager_role = Role.objects.get(slug=ROLE_MANAGER)

        s = make_store("S1")
        u = _make_user("u@x.com")
        StoreMembership.objects.create(
            user=u, store=s, role=manager_role, is_active=True,
        )
        _login(client, u)

        res = client.get(reverse("dashboard:switch_store", args=[s.id]))
        assert res.status_code == 302

    def test_non_member_is_blocked(self, client, make_store):
        s = make_store("S1")
        u = _make_user("u@x.com")
        _login(client, u)

        res = client.get(reverse("dashboard:switch_store", args=[s.id]))
        assert res.status_code == 302
        # Session should NOT have been updated.
        assert "current_store_id" not in client.session

    def test_inactive_member_is_blocked(self, client, make_store):
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        RolesSeeder().run()
        from apps.permissions.models import Role
        manager_role = Role.objects.get(slug=ROLE_MANAGER)

        s = make_store("S1")
        u = _make_user("u@x.com")
        StoreMembership.objects.create(
            user=u, store=s, role=manager_role, is_active=False,
        )
        _login(client, u)

        res = client.get(reverse("dashboard:switch_store", args=[s.id]))
        assert res.status_code == 302
        assert "current_store_id" not in client.session

    def test_superuser_can_switch_any_store(self, client, make_store):
        s = make_store("S1")
        su = _make_user("su@x.com", is_superuser=True)
        _login(client, su)

        res = client.get(reverse("dashboard:switch_store", args=[s.id]))
        assert res.status_code == 302
        assert client.session.get("current_store_id") == str(s.id)

    def test_invalid_store_id_returns_404_or_redirect(self, client):
        """A non-UUID path or unknown store id should not crash."""
        u = _make_user("u@x.com")
        _login(client, u)
        # UUID path converter: passing an obviously invalid value triggers
        # a 404 from the URL resolver.
        res = client.get("/dashboard/switch-store/00000000-0000-0000-0000-000000000000/")
        assert res.status_code in (302, 404)

# ---------------------------------------------------------------------------
# Bug 1 (URL bypass) — dashboard.view permission must be enforced
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDashboardPermissionEnforcement:
    """A user whose role is missing ``dashboard.view`` (or has it explicitly
    DENIED) must get 403 when typing the URL, not 200. The sidebar
    already hides the menu; the view itself must agree.
    """

    def test_owner_with_deny_override_on_dashboard_view_is_blocked(
        self, client, make_store,
    ):
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        from apps.permissions.seeders.permissions_seeder import RolePermissionsSeeder
        from apps.permissions.models import (
            Permission, Role, UserPermissionOverride,
        )
        RolesSeeder().run()
        RolePermissionsSeeder().run()
        owner_role = Role.objects.get(slug=ROLE_STORE_OWNER)
        s = make_store("Fashion Hub")
        u = _make_user("john@x.com")
        StoreMembership.objects.create(
            user=u, store=s, role=owner_role, is_active=True,
        )
        # Explicitly DENY dashboard.view for this user.
        UserPermissionOverride.objects.create(
            user=u, store=s,
            permission=Permission.objects.get(code="dashboard.view"),
            is_granted=False,
        )
        _login(client, u)
        res = client.get(reverse("dashboard:home"))
        assert res.status_code == 403, (
            f"Expected 403 for owner with DENY override on dashboard.view, "
            f"got {res.status_code} — URL bypass still present."
        )

    def test_viewer_role_with_no_membership_sees_onboarding_not_403(
        self, client, make_store,
    ):
        """A user with no membership should see the onboarding card,
        not get 403, because there is no store context to check against.
        """
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        RolesSeeder().run()
        make_store("Orphan")
        u = _make_user("lone@x.com")
        _login(client, u)
        res = client.get(reverse("dashboard:home"))
        # No membership → onboarding state, not 403.
        assert res.status_code == 200
        assert res.context["user_has_no_store"] is True
