"""
Tests for ``apps.permissions.ui.views`` — the role/permission UI views.
"""

from __future__ import annotations

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse

from apps.permissions.models import (
    AuditLog,
    StoreMembership,
    UserPermissionOverride,
)
from apps.permissions.constants import MODIFIER_GRANT

User = get_user_model()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def login_as(client: Client, user) -> Client:
    """Force-login a user (skips password hashing)."""
    client.force_login(user)
    return client


def set_store(client: Client, store) -> None:
    """Persist the current store in the test session."""
    session = client.session
    session["current_store_id"] = str(store.id)
    session.save()


# ---------------------------------------------------------------------------
# RoleListView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRoleListView:
    def test_superuser_sees_all_roles(
        self, superuser, make_store, system_roles, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.get(reverse("role_permission:role_list"))
        assert res.status_code == 200
        # All system roles should be in the context
        assert b"store-owner" in res.content or "store-owner" in res.context["roles"].values_list("slug", flat=True)

    def test_anonymous_redirected(self, rp_client):
        res = rp_client.get(reverse("role_permission:role_list"))
        # LoginRequiredMixin redirects to login (302)
        assert res.status_code in (302, 403)

    def test_non_member_user_blocked(
        self, make_user, make_store, system_roles, rp_client,
    ):
        store = make_store("S")
        # User has no membership in `store`
        user = make_user("u@example.com")
        login_as(rp_client, user)
        set_store(rp_client, store)
        res = rp_client.get(reverse("role_permission:role_list"))
        # No membership → test_func returns False → 403/302
        assert res.status_code in (302, 403)

    def test_search_filter(
        self, superuser, make_store, system_roles, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.get(
            reverse("role_permission:role_list"), {"q": "manager"},
        )
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# RoleDetailView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRoleDetailView:
    def test_superuser_views_role(
        self, superuser, make_store, system_roles, rp_client,
    ):
        s = make_store("S")
        role = system_roles["manager"]
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.get(
            reverse("role_permission:role_detail", kwargs={"role_id": str(role.id)}),
        )
        assert res.status_code == 200
        assert res.context["role"].id == role.id
        assert "grouped_permissions" in res.context
        # Each group should have granted_count + total_count
        for grp in res.context["grouped_permissions"]:
            assert "granted_count" in grp
            assert "total_count" in grp

    def test_nonexistent_role_404(
        self, superuser, make_store, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.get(
            reverse(
                "role_permission:role_detail",
                kwargs={"role_id": "00000000-0000-0000-0000-000000000000"},
            ),
        )
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# RoleCreateView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRoleCreateView:
    def test_get_renders_form(
        self, superuser, make_store, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.get(reverse("role_permission:role_create"))
        assert res.status_code == 200
        assert "form" in res.context

    def test_post_creates_role_and_audit(
        self, superuser, make_store, system_roles, permissions, rp_client,
    ):
        from apps.permissions.models import Role

        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.post(
            reverse("role_permission:role_create"),
            {
                "name": "Sales Lead",
                "description": "desc",
                "level": Role.LEVEL_STAFF,
                "is_active": "on",
                "permissions": [str(permissions["orders.view"].id)],
            },
        )
        assert res.status_code == 302
        assert Role.objects.filter(name="Sales Lead", store=s).exists()
        assert AuditLog.objects.filter(action="role.create").count() == 1

    def test_post_empty_name_rerenders(
        self, superuser, make_store, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        # Slugify of "!!!" → empty string
        res = rp_client.post(
            reverse("role_permission:role_create"),
            {"name": "!!!"},
        )
        # Service raises ValueError → form re-renders with 200
        assert res.status_code == 200


# ---------------------------------------------------------------------------
# RoleUpdateView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRoleUpdateView:
    def test_post_updates_role(
        self, superuser, make_store, system_roles, permissions, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        # Create a custom role
        from apps.permissions.ui.services import create_role
        role = create_role(actor=superuser, store=s, name="Original")
        res = rp_client.post(
            reverse("role_permission:role_edit", kwargs={"role_id": str(role.id)}),
            {
                "name": "Updated",
                "description": "d",
                "level": role.level,
                "is_active": "on",
                "permissions": [],
            },
        )
        assert res.status_code == 302
        role.refresh_from_db()
        assert role.name == "Updated"
        assert AuditLog.objects.filter(action="role.update").count() == 1


# ---------------------------------------------------------------------------
# RoleDeleteView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRoleDeleteView:
    def test_post_soft_deletes_when_active_members(
        self, superuser, make_store, system_roles, make_user, rp_client,
    ):
        from apps.permissions.ui.services import create_role

        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        role = create_role(actor=superuser, store=s, name="Used")
        u = make_user("u@example.com")
        StoreMembership.objects.create(user=u, store=s, role=role, is_active=True)

        res = rp_client.post(
            reverse("role_permission:role_delete", kwargs={"role_id": str(role.id)}),
        )
        assert res.status_code == 302
        role.refresh_from_db()
        assert role.is_active is False
        assert AuditLog.objects.filter(action="role.deactivate").exists()

    def test_post_hard_deletes_when_no_members(
        self, superuser, make_store, system_roles, rp_client,
    ):
        from apps.permissions.models import Role
        from apps.permissions.ui.services import create_role

        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        role = create_role(actor=superuser, store=s, name="Ephemeral")
        rid = role.id
        res = rp_client.post(
            reverse("role_permission:role_delete", kwargs={"role_id": str(role.id)}),
        )
        assert res.status_code == 302
        assert not Role.objects.filter(id=rid).exists()


# ---------------------------------------------------------------------------
# RoleCloneView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRoleCloneView:
    def test_post_clones_role(
        self, superuser, make_store, system_roles, permissions, rp_client,
    ):
        from apps.permissions.ui.services import create_role

        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        source = create_role(actor=superuser, store=s, name="Source")
        from apps.permissions.models import RolePermission
        RolePermission.objects.create(
            role=source, permission=permissions["orders.view"], modifier=MODIFIER_GRANT,
        )

        res = rp_client.post(
            reverse("role_permission:role_clone", kwargs={"role_id": str(source.id)}),
            {"new_name": "Source Copy"},
        )
        assert res.status_code == 302
        assert source.inherits_from_id is None
        # New role should be returned in the redirect
        from apps.permissions.models import Role
        clone = Role.objects.get(name="Source Copy", store=s)
        assert clone.inherits_from_id == source.id
        assert clone.role_permissions.count() == 1


# ---------------------------------------------------------------------------
# RolePermissionToggleView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRolePermissionToggleView:
    def test_ajax_toggles_permission(
        self, superuser, make_store, system_roles, permissions, rp_client,
    ):
        from apps.permissions.ui.services import create_role

        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        role = create_role(actor=superuser, store=s, name="R")
        perm = permissions["orders.view"]

        res = rp_client.post(
            reverse(
                "role_permission:role_toggle_permission",
                kwargs={"role_id": str(role.id)},
            ),
            data=json.dumps({"permission_id": str(perm.id)}),
            content_type="application/json",
        )
        assert res.status_code == 200
        body = res.json()
        assert body["granted"] is True
        # Toggle off
        res = rp_client.post(
            reverse(
                "role_permission:role_toggle_permission",
                kwargs={"role_id": str(role.id)},
            ),
            data=json.dumps({"permission_id": str(perm.id)}),
            content_type="application/json",
        )
        assert res.json()["granted"] is False

    def test_ajax_missing_permission_id(
        self, superuser, make_store, system_roles, rp_client,
    ):
        from apps.permissions.ui.services import create_role

        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        role = create_role(actor=superuser, store=s, name="R")

        res = rp_client.post(
            reverse(
                "role_permission:role_toggle_permission",
                kwargs={"role_id": str(role.id)},
            ),
            data=json.dumps({}),
            content_type="application/json",
        )
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# MemberListView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMemberListView:
    def test_lists_active_members(
        self, superuser, make_store, system_roles, make_user, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        u = make_user("u@example.com")
        StoreMembership.objects.create(
            user=u, store=s, role=system_roles["manager"], is_active=True,
        )
        res = rp_client.get(reverse("role_permission:member_list"))
        assert res.status_code == 200
        assert res.context["members"].count() == 1

    def test_status_filter(
        self, superuser, make_store, system_roles, make_user, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        u = make_user("u@example.com")
        m = StoreMembership.objects.create(
            user=u, store=s, role=system_roles["manager"], is_active=True,
        )
        m.is_active = False
        m.save()

        res = rp_client.get(
            reverse("role_permission:member_list"), {"status": "inactive"},
        )
        assert res.status_code == 200
        assert res.context["members"].count() == 1


# ---------------------------------------------------------------------------
# MemberAddView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMemberAddView:
    def test_get_renders_form(
        self, superuser, make_store, system_roles, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.get(reverse("role_permission:member_add"))
        assert res.status_code == 200
        assert "form" in res.context

    def test_post_adds_member(
        self, superuser, make_store, system_roles, make_user, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        u = make_user("u@example.com")
        res = rp_client.post(
            reverse("role_permission:member_add"),
            {
                "email": "u@example.com",
                "role": str(system_roles["manager"].id),
            },
        )
        assert res.status_code == 302
        assert StoreMembership.objects.filter(
            user=u, store=s, role=system_roles["manager"], is_active=True,
        ).exists()

    def test_post_unknown_email(
        self, superuser, make_store, system_roles, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.post(
            reverse("role_permission:member_add"),
            {
                "email": "missing@example.com",
                "role": str(system_roles["manager"].id),
            },
        )
        # Form validation fails → 400 status returned
        assert res.status_code == 400


# ---------------------------------------------------------------------------
# MemberChangeRoleView (AJAX)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMemberChangeRoleView:
    def test_changes_role(
        self, superuser, make_store, system_roles, make_user, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        u = make_user("u@example.com")
        m = StoreMembership.objects.create(
            user=u, store=s, role=system_roles["manager"], is_active=True,
        )
        res = rp_client.post(
            reverse(
                "role_permission:member_change_role",
                kwargs={"membership_id": str(m.id)},
            ),
            data=json.dumps({"role_id": str(system_roles["viewer"].id)}),
            content_type="application/json",
        )
        assert res.status_code == 200
        m.refresh_from_db()
        assert m.role_id == system_roles["viewer"].id


# ---------------------------------------------------------------------------
# MemberDeactivate / Reactivate
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMemberDeactivateReactivate:
    def test_deactivate(
        self, superuser, make_store, system_roles, make_user, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        u = make_user("u@example.com")
        m = StoreMembership.objects.create(
            user=u, store=s, role=system_roles["manager"], is_active=True,
        )
        res = rp_client.post(
            reverse(
                "role_permission:member_deactivate",
                kwargs={"membership_id": str(m.id)},
            ),
        )
        assert res.status_code == 200
        m.refresh_from_db()
        assert m.is_active is False

    def test_reactivate(
        self, superuser, make_store, system_roles, make_user, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        u = make_user("u@example.com")
        m = StoreMembership.objects.create(
            user=u, store=s, role=system_roles["manager"], is_active=False,
        )
        res = rp_client.post(
            reverse(
                "role_permission:member_reactivate",
                kwargs={"membership_id": str(m.id)},
            ),
        )
        assert res.status_code == 200
        m.refresh_from_db()
        assert m.is_active is True
        assert AuditLog.objects.filter(action="member.reactivate").exists()


# ---------------------------------------------------------------------------
# OverrideListView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOverrideListView:
    def test_superuser_sees_all(
        self, superuser, make_user, make_store, permissions, rp_client,
    ):
        s = make_store("S")
        target = make_user("t@example.com")
        from apps.permissions.ui.services import set_user_override
        set_user_override(
            actor=superuser, target_user=target, store=s,
            permission=permissions["orders.view"], is_granted=True,
        )
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.get(reverse("role_permission:override_list"))
        assert res.status_code == 200
        assert res.context["overrides"].count() == 1

    def test_kind_filter(
        self, superuser, make_user, make_store, permissions, rp_client,
    ):
        s = make_store("S")
        target = make_user("t@example.com")
        from apps.permissions.ui.services import set_user_override
        set_user_override(
            actor=superuser, target_user=target, store=s,
            permission=permissions["orders.view"], is_granted=True,
        )
        set_user_override(
            actor=superuser, target_user=target, store=s,
            permission=permissions["orders.create"], is_granted=False,
        )
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.get(
            reverse("role_permission:override_list"), {"kind": "deny"},
        )
        assert res.status_code == 200
        assert res.context["overrides"].count() == 1


# ---------------------------------------------------------------------------
# OverrideCreate / Update / Delete
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestOverrideCRUD:
    def test_create(
        self, superuser, make_user, make_store, permissions, rp_client,
    ):
        s = make_store("S")
        target = make_user("t@example.com")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.post(
            reverse("role_permission:override_create"),
            {
                "user": str(target.id),
                "permission": str(permissions["orders.view"].id),
                "is_granted": "on",
                "reason": "test",
            },
        )
        assert res.status_code == 302
        assert UserPermissionOverride.objects.filter(
            user=target, permission=permissions["orders.view"], is_granted=True,
        ).exists()

    def test_update(
        self, superuser, make_user, make_store, permissions, rp_client,
    ):
        from apps.permissions.ui.services import set_user_override

        s = make_store("S")
        target = make_user("t@example.com")
        ov = set_user_override(
            actor=superuser, target_user=target, store=s,
            permission=permissions["orders.view"], is_granted=True, reason="r1",
        )
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.post(
            reverse(
                "role_permission:override_edit",
                kwargs={"override_id": str(ov.id)},
            ),
            {
                "user": str(target.id),
                "permission": str(permissions["orders.view"].id),
                # NB: checkbox is OFF → not sent
                "reason": "r2",
            },
        )
        assert res.status_code == 302
        ov.refresh_from_db()
        assert ov.is_granted is False
        assert ov.reason == "r2"

    def test_delete(
        self, superuser, make_user, make_store, permissions, rp_client,
    ):
        from apps.permissions.ui.services import set_user_override

        s = make_store("S")
        target = make_user("t@example.com")
        ov = set_user_override(
            actor=superuser, target_user=target, store=s,
            permission=permissions["orders.view"], is_granted=True,
        )
        oid = ov.id
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.post(
            reverse(
                "role_permission:override_delete",
                kwargs={"override_id": str(ov.id)},
            ),
        )
        assert res.status_code == 302
        assert not UserPermissionOverride.objects.filter(id=oid).exists()


# ---------------------------------------------------------------------------
# PermissionCatalogView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPermissionCatalogView:
    def test_lists_resources(
        self, superuser, make_store, system_roles, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.get(reverse("role_permission:permission_catalog"))
        assert res.status_code == 200
        assert res.context["resources"].count() > 0


# ---------------------------------------------------------------------------
# RoleCreateView / RoleUpdateView — grouped permission context
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRoleFormGroupedPermissions:
    def test_role_create_provides_grouped_permissions(
        self, superuser, make_store, system_roles, permissions, rp_client,
    ):
        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.get(reverse("role_permission:role_create"))
        assert res.status_code == 200
        groups = res.context["grouped_permissions"]
        assert len(groups) > 0
        # Each group has resource, permissions, granted_count, total_count
        for g in groups:
            assert "resource" in g
            assert "permissions" in g
            assert "granted_count" in g
            assert "total_count" in g
            # Each permission has choice (BoundField) and code
            for p in g["permissions"]:
                assert p["choice"] is not None
                assert p["code"]
                assert "id" in p

    def test_role_edit_marks_granted_permissions(
        self, superuser, make_store, system_roles, permissions, rp_client,
    ):
        from apps.permissions.ui.services import create_role
        from apps.permissions.models import RolePermission
        from apps.permissions.constants import MODIFIER_GRANT

        s = make_store("S")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        role = create_role(actor=superuser, store=s, name="Custom")
        RolePermission.objects.create(
            role=role, permission=permissions["orders.view"], modifier=MODIFIER_GRANT,
        )
        res = rp_client.get(
            reverse("role_permission:role_edit", kwargs={"role_id": str(role.id)}),
        )
        assert res.status_code == 200
        groups = res.context["grouped_permissions"]
        # Find the orders.view permission across all groups
        granted = [p for g in groups for p in g["permissions"] if p["code"] == "orders.view"]
        assert granted, "orders.view not present in groups"
        assert granted[0]["granted"] is True


# ---------------------------------------------------------------------------
# AuditLogListView
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAuditLogListView:
    def test_superuser_sees_all(
        self, superuser, make_store, system_roles, permissions, rp_client,
    ):
        from apps.permissions.ui.services import create_role

        s = make_store("S")
        create_role(actor=superuser, store=s, name="R")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.get(reverse("role_permission:audit_log"))
        assert res.status_code == 200
        assert res.context["events"].count() >= 1

    def test_action_filter(
        self, superuser, make_store, system_roles, permissions, rp_client,
    ):
        from apps.permissions.ui.services import create_role

        s = make_store("S")
        create_role(actor=superuser, store=s, name="R")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.get(
            reverse("role_permission:audit_log"), {"action": "role.create"},
        )
        assert res.status_code == 200
        assert all(e.action == "role.create" for e in res.context["events"])


# ---------------------------------------------------------------------------
# AuditLogExportView (superuser only)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAuditLogExportView:
    def test_superuser_exports_csv(
        self, superuser, make_store, system_roles, permissions, rp_client,
    ):
        from apps.permissions.ui.services import create_role

        s = make_store("S")
        create_role(actor=superuser, store=s, name="R")
        login_as(rp_client, superuser)
        set_store(rp_client, s)
        res = rp_client.get(reverse("role_permission:audit_export"))
        assert res.status_code == 200
        assert res["Content-Type"] == "text/csv"
        assert res.content.startswith(b"created_at,action,target_type")
        # The body should include the role.create event we just emitted.
        assert b"role.create" in res.content

    def test_non_superuser_forbidden(
        self, make_user, make_store, system_roles, rp_client,
    ):
        s = make_store("S")
        user = make_user("u@example.com")
        StoreMembership.objects.create(
            user=user, store=s, role=system_roles["store-owner"], is_active=True,
        )
        login_as(rp_client, user)
        set_store(rp_client, s)
        res = rp_client.get(reverse("role_permission:audit_export"))
        assert res.status_code in (302, 403)
