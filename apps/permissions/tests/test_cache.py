"""Tests for the cache layer and version-stamp invalidation."""

from __future__ import annotations

import pytest
from django.core.cache import cache

from apps.permissions.cache import (
    bump_store_plan_version,
    bump_user_version,
    get_store_plan_version,
    get_user_version,
)
from apps.permissions.models import (
    Permission,
    Role,
    RolePermission,
    StoreMembership,
    UserPermissionOverride,
)
from apps.permissions.resolver import PermissionResolver
from apps.permissions.constants import ROLE_MANAGER, ROLE_VIEWER


@pytest.mark.django_db
class TestCacheHelpers:
    def test_bump_user_version_starts_at_2(self, db):
        # Default version is 1 when no key has been set.
        cache.clear()
        assert get_user_version(123) == 1
        new = bump_user_version(123)
        assert new == 2
        assert get_user_version(123) == 2

    def test_bump_user_version_increments(self, db):
        cache.clear()
        bump_user_version(123)
        bump_user_version(123)
        assert get_user_version(123) == 3

    def test_bump_store_plan_version(self, db):
        cache.clear()
        assert get_store_plan_version(456) == 1
        new = bump_store_plan_version(456)
        assert new == 2


@pytest.mark.django_db(transaction=True)
class TestCacheInvalidationSignals:
    def test_role_permission_change_bumps_user(
        self, transactional_db, system_roles, manager_membership, resources,
    ):
        from django.db import transaction
        user, store, _ = manager_membership
        perm = RolePermission(
            role=Role.objects.get(slug=ROLE_MANAGER),
            permission=Permission.objects.get(code="orders.create"),
        )
        version_before = get_user_version(user.id)
        # Wrap in atomic so the on_commit hook fires and the bump happens
        # before we read get_user_version() again.
        with transaction.atomic():
            perm.save()
        # The user-version stamp must have been bumped.
        assert get_user_version(user.id) > version_before

    def test_membership_change_bumps_user_and_store(
        self, transactional_db, system_roles, viewer_role,
    ):
        from django.db import transaction
        from tests.factories import UserFactory
        from apps.stores.models import Store
        u = UserFactory()
        s = Store.objects.create(name="X", status="active")

        u_before = get_user_version(u.id)
        s_before = get_store_plan_version(s.id)
        with transaction.atomic():
            StoreMembership.objects.create(
                user=u, store=s, role=viewer_role, is_active=True,
            )
        assert get_user_version(u.id) > u_before
        assert get_store_plan_version(s.id) > s_before

    def test_user_override_change_bumps_user(
        self, transactional_db, system_roles, viewer_membership, resources,
    ):
        from django.db import transaction
        user, store, _ = viewer_membership
        u_before = get_user_version(user.id)
        with transaction.atomic():
            UserPermissionOverride.objects.create(
                user=user, store=store,
                permission=Permission.objects.get(code="orders.create"),
                is_granted=True,
            )
        assert get_user_version(user.id) > u_before
