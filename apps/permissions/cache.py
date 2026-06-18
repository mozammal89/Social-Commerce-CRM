"""
Cache helpers for the RBAC system.

Strategy:
- Per-user version stamp: bumping it invalidates ALL permission caches
  for that user (no need to enumerate keys).
- Per-store plan version stamp: similar for plan/feature caches.
- Permission/feature sets are stored as Python sets under a single key
  per (user, store, version, plan_version).

This is the "version stamp" pattern: we don't need to delete keys, we just
ignore them because the version changed and a new key is used.
"""

from __future__ import annotations

from functools import wraps
from typing import Callable, TypeVar

from django.core.cache import cache

# 15 minutes. Permission sets change infrequently.
DEFAULT_TTL = 60 * 15

# 24 hours for version stamps — they're tiny and only incremented on change.
VERSION_TTL = 60 * 60 * 24

T = TypeVar("T")


# ---------------------------------------------------------------------------
# Key builders — central place so we can grep / audit / migrate later.
# ---------------------------------------------------------------------------
def user_perm_key(user_id, store_id, version: int) -> str:
    return f"rbac:user:{user_id}:store:{store_id}:perms:v{version}"


def user_feature_key(user_id, store_id, version: int, plan_version: int) -> str:
    return (
        f"rbac:user:{user_id}:store:{store_id}:features"
        f":v{version}:p{plan_version}"
    )


def user_version_key(user_id) -> str:
    return f"rbac:user:{user_id}:version"


def store_plan_version_key(store_id) -> str:
    return f"rbac:store:{store_id}:plan:version"


def user_jwt_perms_key(user_id, version: int) -> str:
    return f"rbac:user:{user_id}:jwt:perms:v{version}"


# ---------------------------------------------------------------------------
# Version-stamp helpers
# ---------------------------------------------------------------------------
def _incr_or_set(key: str, ttl: int = VERSION_TTL) -> int:
    """
    Atomic increment of a counter. If the key doesn't exist, set it to 2
    (we never use 1 so callers can default to 1 on a miss and still know
    they're seeing the original version).
    """
    try:
        return cache.incr(key)
    except ValueError:
        cache.set(key, 2, ttl)
        return 2


def bump_user_version(user_id) -> int:
    """Invalidate every cache entry tied to this user."""
    if user_id is None:
        return 0
    return _incr_or_set(user_version_key(user_id))


def bump_store_plan_version(store_id) -> int:
    """Invalidate plan/feature caches for this store."""
    if store_id is None:
        return 0
    return _incr_or_set(store_plan_version_key(store_id))


def get_user_version(user_id) -> int:
    return cache.get(user_version_key(user_id), 1)


def get_store_plan_version(store_id) -> int:
    return cache.get(store_plan_version_key(store_id), 1)


# ---------------------------------------------------------------------------
# Generic decorator for cacheable service-layer results.
# ---------------------------------------------------------------------------
def cached_permissions(key_fn: Callable[..., str], ttl: int = DEFAULT_TTL):
    """
    Decorator: caches the return value under ``key_fn(*args, **kwargs)``.

    Usage:

        @cached_permissions(key_fn=lambda uid, sid: f"rbac:u{uid}:s{sid}:roles")
        def get_user_roles_in_store(uid, sid):
            ...
    """
    def deco(fn: Callable[..., T]) -> Callable[..., T]:
        @wraps(fn)
        def wrapper(*args, **kwargs) -> T:
            key = key_fn(*args, **kwargs)
            hit = cache.get(key)
            if hit is not None:
                return hit
            val = fn(*args, **kwargs)
            cache.set(key, val, ttl)
            return val

        return wrapper

    return deco