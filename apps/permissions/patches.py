"""
Monkey-patches the User and Store models with RBAC convenience methods.

We add them here (rather than editing the model classes) to:
- Keep the User model migration-free.
- Avoid circular imports (User → permissions → User).

Loaded automatically via ``apps.permissions.apps.PermissionsConfig.ready()``
when ``apps.permissions`` is in INSTALLED_APPS.

API added:

    user.has_permission("orders.create", store=store, obj=obj) -> bool
    user.has_feature("marketing_campaigns", store=store) -> bool
    store.has_feature("marketing_campaigns") -> bool
"""

from __future__ import annotations


def _user_has_permission(self, code: str, store=None, obj=None) -> bool:
    """Instance method: ``user.has_permission('orders.create', store=...)``."""
    from .resolver import PermissionResolver
    return PermissionResolver().check(self, store, code, obj=obj)


def _user_has_feature(self, code: str, store=None) -> bool:
    """Instance method: ``user.has_feature('marketing_campaigns', store=...)``."""
    from .resolver import PermissionResolver
    return PermissionResolver().check_feature(self, store, code)


def _user_grants(self, store=None) -> set[str]:
    """Return the set of permission codes the user has in this store."""
    from .resolver import PermissionResolver
    return PermissionResolver().grants(self, store)


def _store_has_feature(self, code: str) -> bool:
    """Instance method: ``store.has_feature('marketing_campaigns')``."""
    from .services import store_has_feature
    return store_has_feature(self, code)


def install() -> None:
    """Attach RBAC methods to User and Store. Safe to call multiple times."""
    from django.contrib.auth import get_user_model
    from apps.stores.models import Store

    User = get_user_model()

    # Idempotent: only attach if not already present.
    if not hasattr(User, "has_permission"):
        User.has_permission = _user_has_permission
    if not hasattr(User, "has_feature"):
        User.has_feature = _user_has_feature
    if not hasattr(User, "grants"):
        User.grants = _user_grants

    if not hasattr(Store, "has_feature"):
        Store.has_feature = _store_has_feature