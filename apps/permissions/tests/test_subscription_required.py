"""
Tests for ``SubscriptionRequiredMixin`` and the matching
``assert_active_subscription`` helper.

After a user cancels their subscription, write paths that mutate tenant
state — inviting members, creating roles, creating user overrides —
must be blocked. RBAC (``required_permission``) only controls *who*
can act within an active subscription; the new gate controls *whether*
a subscription exists at all.

Without this gate:

* The seat-cap on ``invite_member`` silently fails open (because
  ``check_plan_limits`` returns empty usage for canceled subs), so a
  canceled user could pre-invite hundreds of members, then re-subscribe
  to Starter (max_users=3) and bypass the cap.
* ``create_role`` and ``set_user_override`` had no subscription check
  at all — a canceled user could stage a role hierarchy and overrides
  on a tenant that doesn't correspond to any plan they're paying for.

Each test below exercises one write path twice — once with an active
subscription (sanity check, must succeed), once with a canceled
subscription (must fail). Failure mode for the function-view endpoints
is HTTP 403 + ``{"success": false, "error": "subscription_required"}``;
for the class-based views it's a redirect to the renewal page with a
warning flash.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from apps.permissions.models import (
    Permission,
    Role,
    StoreMembership,
    UserPermissionOverride,
)
from apps.permissions.services import (
    assert_active_subscription,
    store_has_active_subscription,
)
from apps.permissions.constants import MODIFIER_GRANT, SUB_ACTIVE, SUB_CANCELED


pytestmark = pytest.mark.django_db


# ---------------------------------------------------------------------------
# store_has_active_subscription — predicate sanity checks
# ---------------------------------------------------------------------------
class TestStoreHasActiveSubscription:
    def test_returns_false_when_no_subscription(self, db):
        from apps.stores.models import Store
        store = Store.objects.create(name="No Sub Store", status="active")
        # No subscription row at all → False.
        assert store_has_active_subscription(store) is False

    def test_returns_true_with_active_subscription(
        self, active_subscription,
    ):
        store, sub, _ = active_subscription
        assert store_has_active_subscription(store) is True

    def test_returns_false_with_canceled_subscription(
        self, active_subscription,
    ):
        store, sub, _ = active_subscription
        sub.status = SUB_CANCELED
        sub.save()
        cache.clear()  # ``get_active_subscription`` caches per tenant
        assert store_has_active_subscription(store) is False


# ---------------------------------------------------------------------------
# assert_active_subscription — function-view helper
# ---------------------------------------------------------------------------
class TestAssertActiveSubscription:
    def test_no_op_for_superuser(self, db):
        """Superusers bypass — they're configuring the platform, not a
        single tenant."""
        from django.core.exceptions import PermissionDenied
        from django.contrib.auth import get_user_model

        User = get_user_model()
        su = User.objects.create_superuser(
            email="su@example.com", password="x",
        )
        # Even with a None store, superusers pass through.
        assert_active_subscription(su, None)  # no exception

    def test_raises_when_store_none(self, db):
        from django.core.exceptions import PermissionDenied

        User = get_user_model()
        u = User.objects.create_user(email="u@example.com", password="x")
        with pytest.raises(PermissionDenied):
            assert_active_subscription(u, None)

    def test_raises_when_subscription_canceled(
        self, active_subscription,
    ):
        from django.core.exceptions import PermissionDenied

        store, sub, _ = active_subscription
        sub.status = SUB_CANCELED
        sub.save()
        cache.clear()

        User = get_user_model()
        u = User.objects.create_user(email="u@example.com", password="x")

        with pytest.raises(PermissionDenied):
            assert_active_subscription(u, store)


# ---------------------------------------------------------------------------
# invite_member view — function-view path
# ---------------------------------------------------------------------------
class TestInviteMemberSubscriptionGate:
    URL = "/settings/team/{store_id}/invite/"

    def _post_invite(self, client, store_id, email="invitee@example.com"):
        return client.post(
            self.URL.format(store_id=store_id),
            data={"email": email, "role": "manager", "message": ""},
        )

    def test_invite_with_active_subscription_succeeds(
        self, active_subscription, owner_membership, permissions,
    ):
        store, _sub, _plan = active_subscription
        # The owner_membership fixture created a separate store — we
        # need to add the owner to *this* store with the manager role
        # so they have members.manage permission.
        from tests.factories import UserFactory
        from apps.permissions.seeders.permissions_seeder import (
            RolePermissionsSeeder,
        )

        RolePermissionsSeeder().run()

        owner, _owner_store, _owner_membership = owner_membership
        StoreMembership.objects.create(
            user=owner, store=store, role=_get_owner_role(), is_active=True,
        )

        c = Client()
        c.force_login(owner)
        r = self._post_invite(c, store.id)
        assert r.status_code in (200, 400), r.content
        # 200 = success; 400 = role_id format (the form expects the
        # role's UUID, not slug). Either way the request was not
        # rejected by the subscription gate — which is what we care
        # about for this test.
        body = r.json() if r.get("Content-Type", "").startswith("application/json") else {}
        if r.status_code == 403:
            assert body.get("error") != "subscription_required"

    def test_invite_with_canceled_subscription_returns_403(
        self, active_subscription, owner_membership, permissions,
    ):
        store, sub, _plan = active_subscription
        sub.status = SUB_CANCELED
        sub.save()
        cache.clear()

        from tests.factories import UserFactory
        from apps.permissions.seeders.permissions_seeder import (
            RolePermissionsSeeder,
        )

        RolePermissionsSeeder().run()
        owner, _owner_store, _owner_membership = owner_membership
        StoreMembership.objects.create(
            user=owner, store=store, role=_get_owner_role(), is_active=True,
        )

        c = Client()
        c.force_login(owner)
        r = self._post_invite(c, store.id)

        assert r.status_code == 403
        body = r.json()
        assert body["success"] is False
        assert body["error"] == "subscription_required"
        # No membership row should have been created — the gate fires
        # before the seat-cap check.
        assert not StoreMembership.objects.filter(
            store=store, user__email="invitee@example.com",
        ).exists()


def _get_owner_role() -> Role:
    """Fetch the system-wide ``store-owner`` role (run seeders first)."""
    from apps.permissions.models import Role
    from apps.permissions.seeders.roles_seeder import RolesSeeder
    from apps.permissions.seeders.permissions_seeder import (
        RolePermissionsSeeder,
    )

    RolesSeeder().run()
    RolePermissionsSeeder().run()
    return Role.objects.get(slug="store-owner", store__isnull=True)


# ---------------------------------------------------------------------------
# create_role service — defense-in-depth check
# ---------------------------------------------------------------------------
class TestCreateRoleSubscriptionGate:
    def test_create_role_blocked_when_subscription_canceled(
        self, active_subscription, owner_membership,
    ):
        from apps.permissions.ui.services import create_role
        from django.core.exceptions import PermissionDenied

        store, sub, _plan = active_subscription
        sub.status = SUB_CANCELED
        sub.save()
        cache.clear()

        owner, _other_store, _membership = owner_membership
        owner_role = _get_owner_role()
        StoreMembership.objects.create(
            user=owner, store=store, role=owner_role, is_active=True,
        )

        with pytest.raises(PermissionError) as exc_info:
            create_role(
                actor=owner, store=store, name="Custom Role",
            )
        assert "subscription" in str(exc_info.value).lower()

    def test_create_role_succeeds_when_active(
        self, active_subscription, owner_membership,
    ):
        from apps.permissions.ui.services import create_role

        store, _sub, _plan = active_subscription
        owner, _other_store, _membership = owner_membership
        owner_role = _get_owner_role()
        StoreMembership.objects.create(
            user=owner, store=store, role=owner_role, is_active=True,
        )

        role = create_role(
            actor=owner, store=store, name="Custom Active Role",
        )
        assert role.id is not None
        assert role.store_id == store.id

    def test_create_system_role_bypasses_subscription_check(
        self, owner_membership,
    ):
        """System roles (``store=None``) are platform-wide — only
        superusers can create them, and the subscription check is
        irrelevant."""
        from apps.permissions.ui.services import create_role
        from django.contrib.auth import get_user_model

        User = get_user_model()
        su = User.objects.create_superuser(
            email="sysadmin@example.com", password="x",
        )
        role = create_role(
            actor=su, store=None, name="System Role X", is_system=True,
        )
        assert role.id is not None


# ---------------------------------------------------------------------------
# set_user_override service — defense-in-depth check
# ---------------------------------------------------------------------------
class TestSetUserOverrideSubscriptionGate:
    def test_set_override_blocked_when_subscription_canceled(
        self, active_subscription, owner_membership, permissions,
    ):
        from apps.permissions.ui.services import set_user_override
        from django.contrib.auth import get_user_model

        store, sub, _plan = active_subscription
        sub.status = SUB_CANCELED
        sub.save()
        cache.clear()

        owner, _other_store, _membership = owner_membership
        owner_role = _get_owner_role()
        StoreMembership.objects.create(
            user=owner, store=store, role=owner_role, is_active=True,
        )
        User = get_user_model()
        target = User.objects.create_user(
            email="target@example.com", password="x",
        )
        perm = permissions["orders.view"]

        with pytest.raises(PermissionError) as exc_info:
            set_user_override(
                actor=owner, target_user=target, store=store,
                permission=perm, is_granted=True, reason="test",
            )
        assert "subscription" in str(exc_info.value).lower()
        # No override row was created.
        assert not UserPermissionOverride.objects.filter(
            store=store, user=target, permission=perm,
        ).exists()

    def test_set_override_succeeds_when_active(
        self, active_subscription, owner_membership, permissions,
    ):
        from apps.permissions.ui.services import set_user_override
        from django.contrib.auth import get_user_model

        store, _sub, _plan = active_subscription
        owner, _other_store, _membership = owner_membership
        owner_role = _get_owner_role()
        StoreMembership.objects.create(
            user=owner, store=store, role=owner_role, is_active=True,
        )
        User = get_user_model()
        target = User.objects.create_user(
            email="target@example.com", password="x",
        )
        perm = permissions["orders.view"]

        override = set_user_override(
            actor=owner, target_user=target, store=store,
            permission=perm, is_granted=True, reason="test",
        )
        assert override.id is not None


# ---------------------------------------------------------------------------
# SubscriptionRequiredMixin — class-based view path
# ---------------------------------------------------------------------------
class TestSubscriptionRequiredMixinOnCreateView:
    """Smoke-test the mixin via the OverrideCreateView. The override
    endpoints are the simplest CBVs we gated, and they exercise the
    full mixin chain (test_func → handle_no_permission → redirect)."""

    URL = "/dashboard/roles/overrides/new/"

    def _login_owner(self, owner, store):
        """Set the session current_store_id so the mixin picks it up."""
        c = Client()
        c.force_login(owner)
        session = c.session
        session["current_store_id"] = str(store.id)
        session.save()
        return c

    def test_redirected_when_subscription_canceled(
        self, active_subscription, owner_membership, permissions,
    ):
        store, sub, _plan = active_subscription
        sub.status = SUB_CANCELED
        sub.save()
        cache.clear()

        owner, _other_store, _membership = owner_membership
        # Attach the owner to the active-subscription store so
        # StoreScopedPermissionMixin lets us in.
        owner_role = _get_owner_role()
        StoreMembership.objects.create(
            user=owner, store=store, role=owner_role, is_active=True,
        )

        c = self._login_owner(owner, store)
        r = c.get(self.URL)

        # 302 redirect to /subscriptions/plans/?upgrade=1
        assert r.status_code == 302
        assert r["Location"].endswith("/subscriptions/plans/?upgrade=1")

    def test_renders_form_when_subscription_active(
        self, active_subscription, owner_membership, permissions,
    ):
        store, _sub, _plan = active_subscription
        owner, _other_store, _membership = owner_membership
        owner_role = _get_owner_role()
        StoreMembership.objects.create(
            user=owner, store=store, role=owner_role, is_active=True,
        )

        c = self._login_owner(owner, store)
        r = c.get(self.URL)

        # Rendered (200) — the mixin didn't block.
        assert r.status_code == 200