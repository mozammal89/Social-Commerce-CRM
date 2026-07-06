"""
Service-layer helpers for the RBAC system.

These are the functions that views, signals, and admin actions call.
Keeping them out of models.py avoids circular imports (the resolver
imports models; models importing resolvers would break app loading).
"""

from __future__ import annotations

from typing import Iterable

from .exceptions import PlanLimitExceeded
from .models import (
    PlanFeature,
    Role,
    RolePermission,
    StoreMembership,
    Subscription,
)
from .resolver import PermissionResolver


# ---------------------------------------------------------------------------
# Feature gating
# ---------------------------------------------------------------------------
def store_has_feature(store, feature_code: str) -> bool:
    """Return True if `store`'s active subscription plan has `feature_code`."""
    if store is None:
        return False
    sub = getattr(store, "subscription", None)
    if sub is None:
        # No subscription row at all → no features.
        return False
    if not sub.is_active():
        return False
    return PlanFeature.objects.filter(
        plan=sub.plan, feature__code=feature_code,
    ).exists()


def user_has_feature(user, store, feature_code: str) -> bool:
    """A user can use a feature iff their store's plan has it AND they're a member."""
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if not store_has_feature(store, feature_code):
        return False
    if getattr(user, "is_superuser", False):
        return True
    return StoreMembership.objects.filter(
        user=user, store=store, is_active=True,
    ).exists()


# ---------------------------------------------------------------------------
# Permission checks (facade over PermissionResolver)
# ---------------------------------------------------------------------------
def user_has_permission(user, store, code: str, obj=None) -> bool:
    """Single source of truth for 'is this user allowed?'."""
    return PermissionResolver().check(user, store, code, obj=obj)


def user_roles_in_store(user, store) -> list[Role]:
    """Return the user's active roles in this store, ordered by level desc."""
    if user is None or store is None:
        return []
    return list(
        Role.objects.filter(
            memberships__user=user,
            memberships__store=store,
            memberships__is_active=True,
        ).distinct().order_by("-level")
    )


# ---------------------------------------------------------------------------
# Role operations
# ---------------------------------------------------------------------------
def clone_role(
    source: Role,
    *,
    new_name: str,
    new_slug: str,
    store=None,
) -> Role:
    """
    Deep-copy a role into the same store (or another store).

    Always creates a non-system role.
    """
    clone = Role.objects.create(
        name=new_name,
        slug=new_slug,
        description=f"Cloned from {source.name}",
        store=store or source.store,
        is_system=False,
        level=source.level,
        inherits_from=source,
    )
    RolePermission.objects.bulk_create(
        [
            RolePermission(
                role=clone,
                permission=rp.permission,
                modifier=rp.modifier,
            )
            for rp in source.role_permissions.select_related("permission").all()
        ]
    )
    return clone


# ---------------------------------------------------------------------------
# Plan limits
# ---------------------------------------------------------------------------
def assert_within_plan_limit(store, limit_attr: str, current_value: int) -> None:
    """Raise PlanLimitExceeded if the current_value exceeds the plan cap."""
    sub = getattr(store, "subscription", None)
    if sub is None or not sub.is_active():
        raise PlanLimitExceeded(limit_attr, current_value, 0)
    cap = getattr(sub.plan, limit_attr, None)
    if cap and current_value >= cap:
        raise PlanLimitExceeded(limit_attr, current_value, cap)


def plan_limit(store, limit_attr: str) -> int | None:
    """Return the numeric cap, or None if no active subscription.

    Resolves through the tenant-aware subscription lookup so a store
    whose subscription has been promoted to its tenant still gets the
    correct cap. The legacy ``store.subscription`` reverse is ``None``
    for tenant-attached subscriptions — reading it directly would have
    the dashboard's "Seat cap" badge disappear the moment a user
    upgrades.
    """
    from apps.subscriptions.services import get_active_subscription

    sub = get_active_subscription(store)
    if sub is None or not sub.is_active():
        return None
    return getattr(sub.plan, limit_attr, None)


# ---------------------------------------------------------------------------
# Membership operations
# ---------------------------------------------------------------------------
def add_member(user, store, role: Role, *, invited_by=None) -> StoreMembership:
    """Add a user to a store with a given role. Idempotent on (user, store, role)."""
    membership, created = StoreMembership.objects.get_or_create(
        user=user, store=store, role=role,
        defaults={"is_active": True, "invited_by": invited_by},
    )
    if not created and not membership.is_active:
        membership.is_active = True
        membership.save(update_fields=["is_active", "updated_at"])
    return membership


def remove_member(user, store, role: Role) -> bool:
    """Soft-deactivate a membership. Returns True if a row was changed."""
    qs = StoreMembership.objects.filter(user=user, store=store, role=role)
    updated = qs.update(is_active=False)
    return updated > 0


def active_memberships(store) -> "models.QuerySet[StoreMembership]":
    """Return active memberships for ``store``, or all active memberships when ``store`` is None.

    Passing ``store=None`` historically produced a queryset filtered by
    ``store_id IS NULL``, which never matched any real membership (every
    row has a non-null ``store_id``) and silently dropped the user from
    every "already-subscribed?" guard that relied on it. The caller can
    pass ``store=None`` to mean "all stores" by chaining a ``.filter(user=...)``
    afterwards; preserving that contract here keeps the public surface
    intact while fixing the silent zero-row behaviour.
    """
    qs = StoreMembership.objects.filter(is_active=True)
    if store is not None:
        qs = qs.filter(store=store)
    return qs


# ---------------------------------------------------------------------------
# Downgrade impact (used by change_plan to refuse over-cap downgrades)
# ---------------------------------------------------------------------------
def compute_downgrade_impact(scope, new_plan) -> dict:
    """Return the surplus rows that would block a downgrade to ``new_plan``.

    ``scope`` is either a ``Tenant`` (current architecture) or a
    ``Store`` (legacy single-store subscription). For a Tenant we look
    at every non-deleted store under the tenant; for a Store we look
    only at that one store.

    Returns a dict::

        {
            "stores":  [{"id": uuid, "name": str}, ...],
            "users":   [{"id": uuid, "email": str,
                         "store_id": uuid, "store_name": str}, ...],
            "limits":  {"max_stores": int, "max_users": int, ...},
        }

    Conventions (mirroring ``check_plan_limits`` at
    ``apps/subscriptions/services.py:1177-1191``):

    * **Stores** are returned *newest-first* — the UI shows them as the
      ones to consider deleting first (most recently created, typically
      the lower-value ones).
    * **Users** are returned *oldest-first* — soft-deactivate the
      most-tenured non-owner memberships first. This matches the
      "oldest first" semantics used by ``enforce_reserved_seat_cap`` and
      is the most defensive default.
    * **Owners are excluded** from the user count and from the surplus
      list. The store-owner role is identified the same way
      ``check_plan_limits`` identifies it: by user_id of every active
      store-owner membership. (For tenant scope we use the
      tenant's owner field; for store scope we use the active
      store-owner memberships of that one store.)
    * **Reserved seats count** — like ``check_plan_limits``, this
      counts *all* non-owner memberships (active + deactivated) because
      a deactivated row still occupies its seat. So if the user has
      deactivated memberships, those still block the downgrade — they
      must be hard-deleted (or the user upgraded to a higher plan) for
      the downgrade to succeed.

    Used by ``apps.subscriptions.services.downgrade_subscription`` to
    raise ``DowngradeOverCapacity`` with the structured payload, which
    the global exception handler turns into a 400 response carrying
    these lists.
    """
    from .models import Role, StoreMembership
    from apps.stores.models import Store

    max_stores = new_plan.max_stores or 0
    max_users = new_plan.max_users or 0

    # ------------------------------------------------------------------
    # 1) Stores in scope
    # ------------------------------------------------------------------
    if hasattr(scope, "stores"):  # Tenant
        all_stores = list(
            Store.objects.filter(tenant=scope, is_deleted=False).order_by("-created_at")
        )
    else:  # single Store
        all_stores = [scope] if not getattr(scope, "is_deleted", False) else []

    # Surplus stores = everything beyond max_stores, newest-first.
    surplus_stores = all_stores[max_stores:] if max_stores else list(all_stores)

    # ------------------------------------------------------------------
    # 2) Owner user_ids (excluded from the user count)
    # ------------------------------------------------------------------
    if hasattr(scope, "owner") and scope.owner_id:  # Tenant has `.owner`
        owner_ids = {scope.owner_id}
    else:
        owner_role = Role.objects.filter(slug="store-owner", store__isnull=True).first()
        if owner_role:
            owner_ids = set(
                StoreMembership.objects.filter(
                    role=owner_role, is_active=True,
                ).values_list("user_id", flat=True)
            )
        else:
            owner_ids = set()

    # ------------------------------------------------------------------
    # 3) Reserved (active + inactive) non-owner memberships in scope
    # ------------------------------------------------------------------
    in_scope_memberships = (
        StoreMembership.objects
        .filter(store__in=all_stores)
        .exclude(user_id__in=owner_ids)
        .select_related("user", "store")
    )
    # ``check_plan_limits`` semantics: reserved = all rows, not just active.
    # Order newest-first so the *last* ``max_users`` of the list — i.e.
    # the slice below — contains the OLDEST, most-tenured memberships:
    # those are the ones the user is asked to soft-deactivate first.
    surplus_memberships = list(
        in_scope_memberships.order_by("-joined_at")[max_users:]
        if max_users
        else in_scope_memberships
    )

    return {
        "stores": [
            {"id": str(s.id), "name": s.name}
            for s in surplus_stores
        ],
        "users": [
            {
                "id": str(m.user_id),
                "email": m.user.email,
                "store_id": str(m.store_id),
                "store_name": m.store.name,
            }
            for m in surplus_memberships
        ],
        "limits": {
            "max_stores": new_plan.max_stores,
            "max_users": new_plan.max_users,
            "max_products": new_plan.max_products,
            "max_orders_per_month": new_plan.max_orders_per_month,
            "max_warehouses": new_plan.max_warehouses,
        },
    }
