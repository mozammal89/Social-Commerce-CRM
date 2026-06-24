"""
Pytest fixtures for the role/permission management UI tests.
"""

from __future__ import annotations

import pytest
from django.core.cache import cache
from django.test import Client


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def resources(db):
    from django.core.management import call_command
    call_command("sync_permissions", verbosity=0)
    from apps.permissions.models import Resource
    return {r.code: r for r in Resource.objects.all()}


@pytest.fixture
def permissions(resources):
    from apps.permissions.models import Permission
    return {p.code: p for p in Permission.objects.all()}


@pytest.fixture
def system_roles(db):
    from apps.permissions.seeders.roles_seeder import RolesSeeder
    from apps.permissions.seeders.permissions_seeder import RolePermissionsSeeder
    from apps.permissions.models import Role
    RolesSeeder().run()
    RolePermissionsSeeder(verbosity=0).run()
    return {r.slug: r for r in Role.objects.filter(store=None)}


@pytest.fixture
def make_store():
    def _make(name: str = "Test Store"):
        from apps.stores.models import Store
        return Store.objects.create(
            name=name,
            slug=name.lower().replace(" ", "-"),
            status="active",
        )
    return _make


@pytest.fixture
def make_user(db):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    counter = {"n": 0}

    def _make(email: str | None = None, *, is_superuser: bool = False):
        counter["n"] += 1
        if email is None:
            email = f"user{counter['n']}@example.com"
        if is_superuser:
            return User.objects.create_superuser(email=email, password="x")
        return User.objects.create_user(email=email, password="x")
    return _make


@pytest.fixture
def superuser(make_user):
    return make_user("admin@example.com", is_superuser=True)


@pytest.fixture
def owner_with_store(make_user, system_roles, make_store):
    """A superuser with a store and a StoreOwner role assignment."""
    user = make_user("owner@example.com", is_superuser=True)
    store = make_store("Owner Store")
    from apps.permissions.models import StoreMembership
    StoreMembership.objects.create(
        user=user, store=store, role=system_roles["store-owner"], is_active=True,
    )
    return user, store


@pytest.fixture
def rp_client():
    return Client()
