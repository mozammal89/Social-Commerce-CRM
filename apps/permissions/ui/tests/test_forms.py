"""
Tests for ``apps.permissions.ui.forms`` — the role/permission UI forms.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from apps.permissions.models import Role
from apps.permissions.ui.forms import MembershipForm, RoleCloneForm, RoleForm, UserOverrideForm

User = get_user_model()


# ---------------------------------------------------------------------------
# RoleForm
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRoleForm:
    def test_valid_creation(
        self, superuser, make_store, system_roles, permissions,
    ):
        s = make_store("S")
        form = RoleForm(
            data={
                "name": "Sales Lead",
                "description": "d",
                "level": Role.LEVEL_STAFF,
                "is_active": "on",
                "permissions": [str(permissions["orders.view"].id)],
            },
            actor=superuser, store=s,
        )
        assert form.is_valid(), form.errors

    def test_duplicate_slug_rejected(
        self, superuser, make_store, system_roles,
    ):
        s = make_store("S")
        Role.objects.create(name="Custom", slug="custom", store=s)
        form = RoleForm(
            data={
                "name": "Custom",
                "level": Role.LEVEL_STAFF,
                "is_active": "on",
            },
            actor=superuser, store=s,
        )
        assert not form.is_valid()
        assert "name" in form.errors

    def test_superuser_sees_is_system(
        self, superuser, make_store,
    ):
        # is_system is controlled by the view, not the form. The form
        # never exposes it directly.
        form = RoleForm(actor=superuser, store=None)
        assert "is_system" not in form.fields

    def test_non_superuser_no_is_system(
        self, make_user, make_store,
    ):
        u = make_user("u@example.com")
        form = RoleForm(actor=u, store=None)
        assert "is_system" not in form.fields


# ---------------------------------------------------------------------------
# RoleCloneForm
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRoleCloneForm:
    def test_valid_name(self):
        form = RoleCloneForm(data={"new_name": "Sales Copy"})
        assert form.is_valid()

    def test_empty_name_invalid(self):
        form = RoleCloneForm(data={"new_name": ""})
        assert not form.is_valid()


# ---------------------------------------------------------------------------
# MembershipForm
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestMembershipForm:
    def test_valid_existing_user(
        self, superuser, make_user, make_store, system_roles,
    ):
        s = make_store("S")
        u = make_user("u@example.com")
        form = MembershipForm(
            data={
                "email": "u@example.com",
                "role": str(system_roles["manager"].id),
            },
            store=s,
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data["_user"].id == u.id

    def test_unknown_email_invalid(
        self, superuser, make_store, system_roles,
    ):
        s = make_store("S")
        form = MembershipForm(
            data={
                "email": "missing@example.com",
                "role": str(system_roles["manager"].id),
            },
            store=s,
        )
        assert not form.is_valid()
        assert "email" in form.errors

    def test_duplicate_active_membership_invalid(
        self, superuser, make_user, make_store, system_roles,
    ):
        s = make_store("S")
        u = make_user("dup@example.com")
        from apps.permissions.models import StoreMembership
        StoreMembership.objects.create(
            user=u, store=s, role=system_roles["manager"], is_active=True,
        )
        form = MembershipForm(
            data={
                "email": "dup@example.com",
                "role": str(system_roles["manager"].id),
            },
            store=s,
        )
        assert not form.is_valid()
        assert "email" in form.errors


# ---------------------------------------------------------------------------
# UserOverrideForm
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestUserOverrideForm:
    def test_valid_create(
        self, superuser, make_user, make_store, permissions,
    ):
        s = make_store("S")
        target = make_user("t@example.com")
        form = UserOverrideForm(
            data={
                "user": str(target.id),
                "permission": str(permissions["orders.view"].id),
                "is_granted": "on",
                "reason": "test",
            },
            actor=superuser, store=s,
        )
        assert form.is_valid(), form.errors

    def test_valid_update_keeps_user_disabled(
        self, superuser, make_user, make_store, permissions,
    ):
        from apps.permissions.ui.services import set_user_override

        s = make_store("S")
        target = make_user("t@example.com")
        ov = set_user_override(
            actor=superuser, target_user=target, store=s,
            permission=permissions["orders.view"], is_granted=True,
        )
        form = UserOverrideForm(
            instance=ov,
            data={
                "user": str(target.id),
                "permission": str(permissions["orders.view"].id),
                "is_granted": "on",
                "reason": "updated",
            },
            actor=superuser, store=s,
        )
        assert form.is_valid(), form.errors
        # When editing, user field should be locked
        assert form.fields["user"].disabled is True

    def test_fresh_instance_does_not_crash(
        self, superuser, make_store, permissions,
    ):
        """A new (unsaved) instance has no user; form should not crash."""
        s = make_store("S")
        target = User.objects.create(email="x@example.com")
        form = UserOverrideForm(
            data={
                "user": str(target.id),
                "permission": str(permissions["orders.view"].id),
                "is_granted": "on",
            },
            actor=superuser, store=s,
        )
        assert form.is_valid(), form.errors
