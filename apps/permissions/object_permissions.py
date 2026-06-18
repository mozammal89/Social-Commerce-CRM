"""
Object-level permission checkers.

A checker is a function ``(user, store, code: str, obj) -> bool`` that
returns True if `user` is allowed to perform `code` on `obj`.

Checkers are registered per-resource via the ``@register_checker`` decorator.
By default there is no checker for any resource → pass-through (the role
permission is sufficient). Register a checker to tighten access.

Example:

    @register_checker("orders")
    def order_object_checker(user, store, code, order):
        if user_has_manager_level(user, store):
            return True
        return order.assignees.filter(pk=user.pk).exists()

This file also ships built-in checkers for ``orders`` and ``customers`` that
match common CRM semantics. Apps are free to override or extend.
"""

from __future__ import annotations

from typing import Callable, Dict, Optional

# Public type alias
Checker = Callable[[object, object, str, object], bool]

# Internal registry
_checkers: Dict[str, Checker] = {}


def register_checker(resource_code: str):
    """
    Decorator: register a checker for a resource.

    Usage:

        @register_checker("orders")
        def order_object_checker(user, store, code, obj):
            ...
    """
    def deco(fn: Checker) -> Checker:
        _checkers[resource_code] = fn
        return fn

    return deco


def get_object_checker(resource_code: str) -> Optional[Checker]:
    """Return the checker registered for a resource, or None."""
    return _checkers.get(resource_code)


def clear_checkers() -> None:
    """Clear all registered checkers. Test-only helper."""
    _checkers.clear()


def list_registered() -> list[str]:
    """Return the list of resource codes with a registered checker."""
    return sorted(_checkers.keys())


# ---------------------------------------------------------------------------
# Built-in checkers
# ---------------------------------------------------------------------------
def _user_role_level(user, store) -> int:
    """
    Return the user's highest active role level in `store`, or 0 if none.
    Lazy import to avoid app-loading-order issues.
    """
    from .models import StoreMembership

    return (
        StoreMembership.objects.filter(
            user=user, store=store, is_active=True,
        )
        .order_by("-role__level")
        .values_list("role__level", flat=True)
        .first()
        or 0
    )


@register_checker("orders")
def order_object_checker(user, store, code: str, order) -> bool:
    """
    Default order object checker.

    - Manager+ (level >= 60) sees everything in the store.
    - Sales Agent or below: only sees orders they're assigned to.

    `order.assignees` is an M2M to User; we look for the relation. If the
    app doesn't define `assignees`, the checker falls back to the role-level
    rule.
    """
    if user is None or store is None or order is None:
        return False

    level = _user_role_level(user, store)
    if level >= 60:  # Manager+
        return True

    # Sales Agent and below: only assigned orders are visible.
    assignees = getattr(order, "assignees", None)
    if assignees is None:
        # No assignees relation on this Order model → fall back to the
        # store-level rule: managers see all, lower roles don't see any.
        return False

    try:
        return assignees.filter(pk=user.pk).exists()
    except Exception:
        return False


@register_checker("customers")
def customer_object_checker(user, store, code: str, customer) -> bool:
    """
    Default customer object checker.

    - Manager+ (level >= 60) sees all customers in the store.
    - Customer Support: only customers where they are the support agent.
    """
    if user is None or store is None or customer is None:
        return False

    level = _user_role_level(user, store)
    if level >= 60:
        return True

    support_agent_id = getattr(customer, "support_agent_id", None)
    return support_agent_id == getattr(user, "id", None)


# ---------------------------------------------------------------------------
# Future row-level hook — placeholder.
# If we ever adopt per-row grants (django-guardian style), plug them in here.
# ---------------------------------------------------------------------------
def has_row_perm(user, store, perm_code: str, obj) -> bool:
    """Hook for future per-row grants. Always False for now."""
    return False
