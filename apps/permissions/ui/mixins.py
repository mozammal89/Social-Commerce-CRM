"""
Reusable mixins for the role/permission management views.

These mixins encapsulate the access-control logic that distinguishes
super-admin (cross-store) views from store-admin (single-store) views.
All views should inherit from one of these.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from apps.permissions.models import StoreMembership
from apps.permissions.services import user_has_permission
from apps.stores.models import Store


class DashboardAccessMixin(LoginRequiredMixin, UserPassesTestMixin):
    """
    Base mixin: requires login and resolves a currently active store.

    For superusers, falls back to the first available store if no
    ``current_store_id`` is in the session. For regular users, the
    session must contain a store they are an active member of.
    """

    store_session_key = "current_store_id"

    def test_func(self) -> bool:
        return self.request.user.is_authenticated

    def get_current_store(self):
        """
        Resolve the active store from the session, or fall back to:
        - superuser: any non-deleted store
        - regular user: first store they have an active membership for
        """
        user = self.request.user
        store_id = self.request.session.get(self.store_session_key)

        if user.is_superuser:
            qs = Store.objects.filter(is_deleted=False)
            if store_id:
                store = qs.filter(id=store_id).first()
                if store is not None:
                    return store
            return qs.order_by("name").first()

        # Regular user: must have an active membership in the requested store
        if store_id:
            store = get_object_or_404(Store, id=store_id, is_deleted=False)
            is_member = StoreMembership.objects.filter(
                user=user, store=store, is_active=True,
            ).exists()
            if is_member:
                return store
            return None

        # No session: pick first active membership
        membership = (
            StoreMembership.objects
            .filter(user=user, is_active=True, store__is_deleted=False)
            .select_related("store")
            .order_by("store__name")
            .first()
        )
        return membership.store if membership else None


class StoreScopedPermissionMixin(DashboardAccessMixin):
    """
    Enforces a specific permission code within the active store.

    Subclasses set ``required_permission``. Superusers always pass.
    Regular users must have the permission in the current store.
    """

    required_permission: str | None = None

    def test_func(self) -> bool:
        if not super().test_func():
            return False
        if self.request.user.is_superuser:
            return True
        if not self.required_permission:
            return True
        store = self.get_current_store()
        if store is None:
            return False
        return user_has_permission(
            self.request.user, store, self.required_permission,
        )


class SuperuserOnlyMixin(DashboardAccessMixin):
    """Restricts access to Django superusers only."""

    def test_func(self) -> bool:
        if not super().test_func():
            return False
        return self.request.user.is_superuser

    def dispatch(self, request, *args: Any, **kwargs: Any):
        if not self.test_func():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


def get_user_stores_for_admin(user):
    """
    Stores a user can administer roles for.

    - Superusers: all non-deleted stores.
    - Store admins: only stores they hold an active membership in.
    """
    if user.is_superuser:
        return Store.objects.filter(is_deleted=False).order_by("name")

    member_store_ids = (
        StoreMembership.objects
        .filter(user=user, is_active=True)
        .values_list("store_id", flat=True)
    )
    return (
        Store.objects
        .filter(id__in=list(member_store_ids), is_deleted=False)
        .distinct()
        .order_by("name")
    )
