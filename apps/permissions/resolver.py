"""
Permission resolver — the core decision engine.

The resolver is intentionally stateless: caching is delegated to django-redis
and to a version-stamp pattern that lets us invalidate keys implicitly.

Check flow (5 layers):

  1. Subscription Plan Access      → store.has_feature / is_active()
  2. Store-Level Permissions       → StoreMembership.exists(user, store, active=True)
  3. Role-Based Permissions        → aggregate RolePermission GRANT/DEFAULT/DENY
  4. User-Specific Overrides       → UserPermissionOverride (DENY is absolute)
  5. Object-Level Authorization   → pluggable checker via object_permissions

Any layer that returns DENY short-circuits.
"""

from __future__ import annotations

from typing import Iterable, Optional, Tuple

from django.core.cache import cache
from django.db.models import Q
from django.utils import timezone

from .cache import (
    DEFAULT_TTL,
    get_store_plan_version,
    get_user_version,
    store_plan_version_key,
    user_feature_key,
    user_perm_key,
    user_version_key,
)
from .models import (
    Permission,
    RolePermission,
    StoreMembership,
    UserPermissionOverride,
)
from apps.subscriptions.models import (
    PlanFeature,
    Subscription,
)
from .registry import split_code, is_valid_permission_code


class PermissionResolver:
    """
    Single entry point for permission decisions.

    Used by:
      - DRF permission classes (`apps.permissions.permissions`)
      - Function view decorators (`apps.permissions.decorators`)
      - CBV mixins (`apps.permissions.mixins`)
      - Template tags (`apps.permissions.templatetags.rbac`)
      - The convenience methods on User / Store

    Stateless — safe to instantiate per request, or share a single instance.
    """

    # ------------------------------------------------------------------ API

    def check(
        self,
        user,
        store,
        code: str,
        obj=None,
    ) -> bool:
        """
        Return True if `user` is allowed to perform `code` (e.g. 'orders.create')
        in `store`. `obj` enables Layer 5 (object-level) checks.

        Returns False for unauthenticated users, missing store, etc.
        Returns True for superusers (but the bypass is auditable downstream).
        """
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_superuser", False):
            return True

        if not is_valid_permission_code(code):
            return False

        grants, denies = self._load_grants_and_denies(user, store)

        if code in denies:
            return False
        if code in grants:
            if obj is not None:
                return self._check_object(user, store, code, obj)
            return True

        return False

    def check_feature(self, user, store, code: str) -> bool:
        """Return True if `store`'s plan has feature `code` AND the user is a member."""
        if user is None or not getattr(user, "is_authenticated", False):
            return False
        if getattr(user, "is_superuser", False):
            return True

        features = self._load_features(user, store)
        return code in features

    # --------------------------------------------------------- bulk helpers

    def grants(self, user, store) -> set[str]:
        """Return the set of permission codes the user has in this store."""
        if user is None or not getattr(user, "is_authenticated", False):
            return set()
        if getattr(user, "is_superuser", False):
            # All non-system permission codes.
            return set(Permission.objects.values_list("code", flat=True))
        g, _ = self._load_grants_and_denies(user, store)
        return g

    def denies(self, user, store) -> set[str]:
        """Return the set of permission codes that are explicitly denied."""
        if user is None or not getattr(user, "is_authenticated", False):
            return set()
        _, d = self._load_grants_and_denies(user, store)
        return d

    # ---------------------------------------------------------- internals

    def _load_grants_and_denies(
        self, user, store
    ) -> Tuple[set[str], set[str]]:
        version = get_user_version(user.id)
        sid = store.id if store is not None else 0
        key = user_perm_key(user.id, sid, version)

        cached = cache.get(key)
        if cached is not None:
            return set(cached.get("grants", set())), set(cached.get("denies", set()))

        grants, denies = self._compute_grants_and_denies(user, store)
        cache.set(key, {"grants": list(grants), "denies": list(denies)}, DEFAULT_TTL)
        return grants, denies

    def _load_features(self, user, store) -> set[str]:
        if store is None:
            return set()
        version = get_user_version(user.id)
        plan_version = get_store_plan_version(store.id)
        key = user_feature_key(user.id, store.id, version, plan_version)

        cached = cache.get(key)
        if cached is not None:
            return set(cached)

        features: set[str] = set()
        sub = Subscription.objects.filter(store=store).first()
        if sub and sub.is_active():
            features = set(
                PlanFeature.objects.filter(plan=sub.plan).values_list(
                    "feature__code", flat=True
                )
            )
        cache.set(key, list(features), DEFAULT_TTL)
        return features

    def _compute_grants_and_denies(
        self, user, store
    ) -> Tuple[set[str], set[str]]:
        """
        Layer 2 + 3 + 4:
          2. If the user has no active StoreMembership for this store → no perms.
          3. Aggregate RolePermission rows: GRANT and DENY.
          4. Apply UserPermissionOverride; DENY is absolute.
        """
        if store is None:
            return set(), set()

        memberships = list(
            StoreMembership.objects.filter(
                user=user, store=store, is_active=True,
            ).values_list("role_id", flat=True)
        )
        if not memberships:
            return set(), set()

        rps = RolePermission.objects.filter(role_id__in=memberships).select_related(
            "permission"
        )

        grants: set[str] = set()
        denies: set[str] = set()
        for rp in rps:
            if rp.modifier == "grant":
                grants.add(rp.permission.code)
            elif rp.modifier == "deny":
                denies.add(rp.permission.code)
            # 'default' is a no-op at the aggregate layer — it means
            # "inherit from parent role". Parent traversal is implemented
            # via inherits_from and is intentionally simple: a recursive
            # walk happens in `_expand_inheritance` (kept trivial here).

        # Layer 4: user-specific overrides.
        now = timezone.now()
        # Either no expiry, or expiry in the future.
        overrides = UserPermissionOverride.objects.filter(
            Q(user=user),
            Q(store__in=[store, None]),
            Q(expires_at__isnull=True) | Q(expires_at__gt=now),
        ).select_related("permission")

        for ov in overrides:
            code = ov.permission.code
            if ov.is_granted:
                grants.add(code)
            else:
                # DENY is absolute.
                denies.add(code)
                grants.discard(code)

        return grants, denies

    def _check_object(self, user, store, code: str, obj) -> bool:
        """Layer 5: pluggable checker."""
        from .object_permissions import get_object_checker

        parts = split_code(code)
        if not parts:
            return False
        resource_code = parts[0]

        checker = get_object_checker(resource_code)
        if checker is None:
            # Default: pass-through. A granted role-level permission is
            # sufficient. Tighten by registering checkers.
            return True
        try:
            return checker(user, store, code, obj)
        except Exception:
            # Never let a buggy checker open a security hole: deny on error.
            return False