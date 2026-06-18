"""
DRF permission classes for the RBAC system.

Usage examples:

    class OrderViewSet(viewsets.ModelViewSet):
        permission_classes = [IsStoreMember, HasPermission]
        permission_code = "orders.view"
        object_permission_code = "orders.update"

        def get_permissions(self):
            if self.action == "create":
                return [IsStoreMember(), HasFeature.with_code("orders.create")]
            return super().get_permissions()

    class CampaignView(APIView):
        permission_classes = [IsStoreMember, HasFeature]
        required_feature = "marketing_campaigns"
"""

from __future__ import annotations

import logging

from rest_framework.permissions import BasePermission

from .resolver import PermissionResolver


logger = logging.getLogger("apps.permissions")

_resolver = PermissionResolver()


class HasPermission(BasePermission):
    """
    View-level: ``view.permission_code = "orders.view"``.

    Object-level: set ``view.object_permission_code = "orders.update"`` and
    the class will call ``resolver.check(user, store, code, obj=instance)``.

    Fail-closed: if no permission code is configured (neither on the view
    nor on the class), the check returns ``False`` and a WARNING is logged.
    This catches the bug class "a view forgot to declare its code".
    """

    permission_code: str | None = None
    object_permission_code: str | None = None
    message = "You do not have permission to perform this action."

    @classmethod
    def with_code(cls, code: str):
        """Subclass factory: ``HasPermission.with_code('orders.create')``."""
        return type(f"HasPermission_{code}", (cls,), {"permission_code": code})

    @classmethod
    def with_object_code(cls, code: str):
        return type(
            f"HasObjectPermission_{code}",
            (cls,),
            {"object_permission_code": code, "permission_code": None},
        )

    def has_permission(self, request, view):
        code = self._view_code(view)
        if not code:
            logger.warning(
                "rbac.no_code view=%s class=%s — HasPermission has no code "
                "configured; failing closed.",
                getattr(view, "__qualname__", repr(view)),
                type(self).__name__,
            )
            return False
        return _resolver.check(
            request.user,
            getattr(request, "store", None),
            code,
        )

    def has_object_permission(self, request, view, obj):
        code = self.object_permission_code or self._view_code(view)
        if not code:
            return False
        return _resolver.check(
            request.user,
            getattr(request, "store", None),
            code,
            obj=obj,
        )

    def _view_code(self, view):
        # View-level attribute wins; fall back to class default.
        return getattr(view, "permission_code", None) or self.permission_code


class HasFeature(BasePermission):
    """View-level: ``view.required_feature = "marketing_campaigns"``.

    Fail-closed when no feature is configured.
    """

    required_feature: str | None = None
    message = "This feature is not available on your current plan."

    @classmethod
    def with_feature(cls, feature_code: str):
        return type(
            f"HasFeature_{feature_code}",
            (cls,),
            {"required_feature": feature_code},
        )

    def has_permission(self, request, view):
        feat = getattr(view, "required_feature", None) or self.required_feature
        if not feat:
            logger.warning(
                "rbac.no_feature view=%s class=%s — HasFeature has no feature "
                "configured; failing closed.",
                getattr(view, "__qualname__", repr(view)),
                type(self).__name__,
            )
            return False
        return _resolver.check_feature(
            request.user, getattr(request, "store", None), feat,
        )


class IsStoreMember(BasePermission):
    """User must be an active member of the current store."""

    message = "You are not a member of this store."

    def has_permission(self, request, view):
        store = getattr(request, "store", None)
        if not store:
            # Fail-closed: a store-scoped view without a resolved store
            # cannot be safely authorized. Caller must use StoreContextMixin
            # or @current_store to set request.store.
            return False
        if request.user.is_superuser:
            return True
        from .models import StoreMembership

        return StoreMembership.objects.filter(
            user=request.user, store=store, is_active=True,
        ).exists()


class HasStoreRole(BasePermission):
    """
    User must hold an active role in the current store with level >= min_level.

    Usage:

        permission_classes = [HasStoreRole.with_level(60)]  # Manager+
    """

    min_level: int = 0
    message = "Your role is not authorized for this action."

    @classmethod
    def with_level(cls, min_level: int):
        return type(
            f"HasStoreRoleMin{min_level}",
            (cls,),
            {"min_level": min_level},
        )

    def has_permission(self, request, view):
        store = getattr(request, "store", None)
        if not store:
            return False
        if request.user.is_superuser:
            return True
        from .models import StoreMembership

        return StoreMembership.objects.filter(
            user=request.user,
            store=store,
            is_active=True,
            role__level__gte=self.min_level,
        ).exists()