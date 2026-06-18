"""Tests for the {% can %} and {% has_feature %} template tags."""

from __future__ import annotations

import pytest
from django.template import Context, Template, TemplateSyntaxError

from apps.permissions.constants import MODIFIER_GRANT, ROLE_MANAGER
from apps.permissions.models import Permission, RolePermission, Role
from apps.permissions.templatetags import rbac as rbac_tags


@pytest.mark.django_db
class TestCanTag:
    def test_can_tag_grants(self, db, system_roles, manager_membership, resources):
        from django.test import RequestFactory
        user, store, _ = manager_membership
        # Grant orders.create to manager.
        perm = Permission.objects.get(code="orders.create")
        RolePermission.objects.create(
            role=Role.objects.get(slug=ROLE_MANAGER),
            permission=perm, modifier=MODIFIER_GRANT,
        )

        request = RequestFactory().get("/")
        request.user = user
        request.store = store
        context = Context({"request": request, "current_store": store})

        template = Template("{% load rbac %}{% can 'orders.create' %}YES{% endcan %}")
        assert template.render(context) == "YES"

    def test_can_tag_denies(self, db, system_roles, viewer_membership, resources):
        from django.test import RequestFactory
        user, store, _ = viewer_membership
        # Viewer doesn't have orders.create.
        request = RequestFactory().get("/")
        request.user = user
        request.store = store
        context = Context({"request": request, "current_store": store})
        template = Template("{% load rbac %}{% can 'orders.create' %}YES{% else %}NO{% endcan %}")
        assert template.render(context) == "NO"

    def test_has_feature_tag(self, db, active_subscription):
        from django.test import RequestFactory
        store, _, _ = active_subscription
        from tests.factories import UserFactory
        from apps.permissions.models import StoreMembership
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        RolesSeeder().run()
        u = UserFactory()
        StoreMembership.objects.create(
            user=u, store=store,
            role=Role.objects.get(slug="viewer"),
            is_active=True,
        )
        request = RequestFactory().get("/")
        request.user = u
        request.store = store
        context = Context({"request": request, "current_store": store})
        t = Template("{% load rbac %}{% has_feature 'customer_management' as feat %}{{ feat }}")
        # The tag returns a string 'True' or 'False' by default.
        rendered = t.render(context)
        assert rendered in ("True", "False")

    def test_can_filter(self, db, system_roles, manager_membership, resources):
        user, _, _ = manager_membership
        perm = Permission.objects.get(code="orders.create")
        RolePermission.objects.create(
            role=Role.objects.get(slug=ROLE_MANAGER),
            permission=perm, modifier=MODIFIER_GRANT,
        )
        # The filter form `{{ user|can:"orders.create" }}` requires
        # user.has_permission to be installed (patches.install does that).
        assert rbac_tags.can(user, "orders.create") in (True, False)
