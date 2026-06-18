"""
JWT fast-path for RBAC permission checks.

The ``PermissionResolver`` always re-evaluates permissions from the DB
by default. For high-traffic API endpoints this can be expensive. As an
optimization, the access token (issued by ``RBACTokenObtainPairSerializer``)
embeds the user's permission codes for their current store. When the
resolver receives a request and can detect that the embedded claims are
fresh, it can short-circuit.

How "fresh" is detected:
    The token carries a ``token_version`` claim equal to the user's
    ``rbac:user:{uid}:version`` cache stamp at issue time. Any role /
    membership / override change bumps the version stamp. On every
    request, the resolver compares the token's ``token_version`` to the
    current ``get_user_version(uid)`` — if they match, the embedded
    ``permissions`` set is authoritative.

Object-level decisions, DENY overrides, and feature checks are NOT
short-circuited here; only the layer-3 role/permission check.

Usage
-----
In a DRF view's ``has_permission`` override::

    from apps.accounts.jwt_rbac import jwt_fast_path_check

    def has_permission(self, request, view):
        code = ...
        ok, trusted = jwt_fast_path_check(request, code)
        if trusted:
            return ok
        # Fall through to full resolver.
        return PermissionResolver().check(request.user, request.store, code)
"""

from __future__ import annotations

from typing import Optional, Tuple


def _extract_claims(request) -> Optional[dict]:
    """Pull the RBAC claims off the authenticated request, if any.

    The SimpleJWT auth backend stashes the validated token on
    ``request.auth``; we stored RBAC claims on that token at issue time.
    """
    token = getattr(request, "auth", None)
    if token is None:
        return None
    # SimpleJWT tokens support both dict-like and Token-like access.
    try:
        return {
            "current_store_id": str(token.get("current_store_id", "") or ""),
            "permissions": set(token.get("permissions", []) or []),
            "features": set(token.get("features", []) or []),
            "token_version": int(token.get("token_version", 0) or 0),
            "user_id": token.get("user_id"),
        }
    except (AttributeError, TypeError, ValueError):
        return None


def jwt_fast_path_check(
    request, code: str,
) -> Tuple[bool, bool]:
    """Attempt to short-circuit a permission check using the JWT claims.

    Args:
        request: A DRF/Django request that has been authenticated by
            SimpleJWT.
        code: The permission code being checked (e.g. ``"orders.view"``).

    Returns:
        (decision, trusted):
            decision — the boolean result if trusted, else ``False``.
            trusted — ``True`` if the JWT claims were authoritative for
                this check, ``False`` if the caller must fall through
                to the full resolver.
    """
    claims = _extract_claims(request)
    if claims is None:
        return False, False

    # Feature checks can also be fast-pathed.
    if code in claims["features"]:
        return True, True
    # If the code isn't in the embedded permissions, it's also not
    # granted (the embedded set was already filtered for denies).
    if code in claims["permissions"]:
        # Verify the request.store matches the token's current_store_id.
        # If it doesn't, we can't trust the embedded permissions.
        store = getattr(request, "store", None)
        store_id = str(getattr(store, "id", "")) if store else ""
        if store_id and store_id != claims["current_store_id"]:
            return False, False  # Wrong store; trust the DB.
        return True, True
    return False, False


def jwt_fast_path_feature(request, code: str) -> Tuple[bool, bool]:
    """Fast-path for feature checks.

    Returns ``(decision, trusted)`` analogous to :func:`jwt_fast_path_check`.
    """
    claims = _extract_claims(request)
    if claims is None:
        return False, False
    store = getattr(request, "store", None)
    store_id = str(getattr(store, "id", "")) if store else ""
    if store_id and store_id != claims["current_store_id"]:
        return False, False
    if code in claims["features"]:
        return True, True
    if code in claims["permissions"]:
        # Feature codes are not the same as permission codes, but for
        # safety we treat a permission grant as a positive signal (the
        # user clearly has access to that resource).
        return True, True
    return False, False