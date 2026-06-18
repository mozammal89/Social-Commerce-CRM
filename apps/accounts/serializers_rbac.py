"""
RBAC-aware JWT token serializer.

This module provides :class:`RBACTokenObtainPairSerializer`, an opt-in
replacement for ``CustomTokenObtainPairSerializer`` that embeds the
RBAC permission claims directly in the access token. This enables a
"fast path" in the permission resolver: when a request arrives with a
JWT whose ``current_store_id`` matches ``request.store.id``, the
resolver can trust the token's ``permissions`` set without re-querying
the DB.

Why opt-in?
-----------
The existing ``apps.accounts.serializers.CustomTokenObtainPairSerializer``
is wired into ``urls_api.py``. Swapping it for this one is a one-line
change in the URL config (see project README). Keeping this in a
separate module means existing tests/users are not broken until the
operator is ready to migrate.

Embedded claims (alongside SimpleJWT's default ``user_id``, ``exp``,
``iat``, ``jti``, ``token_type``):

    email            str    — user's email (stable, low-cardinality)
    is_superuser     bool   — superuser bypass flag
    stores           list   — store IDs the user is an active member of
    current_store_id str    — most recently joined active store (or "")
    permissions      list   — sorted permission codes the user has in
                              ``current_store_id`` (denies excluded)
    features         list   — sorted feature codes the user's
                              ``current_store_id`` plan unlocks
    token_version    int    — user's RBAC version stamp (see below)

The ``token_version`` claim lets the resolver detect a stale token:
when the user's ``rbac:user:{uid}:version`` cache stamp differs from
``token_version``, the resolver falls back to the DB path. This is
how role changes propagate on a short JWT TTL without forcing every
user to re-login.

Object-level decisions, DENY overrides, and ``expires_at`` time-boxes
are NOT embedded — they are always re-evaluated server-side. The
token only carries the stable, low-cardinality permission codes.
"""

from __future__ import annotations

from rest_framework_simplejwt.serializers import TokenObtainPairSerializer


def _collect_user_claims(user) -> dict:
    """Compute the RBAC claims to embed in the access token.

    Returns an empty dict for anonymous or unsaved users (defensive).
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return {}
    if not getattr(user, "pk", None):
        return {}

    # Lazy imports keep apps.permissions import-light at serializer
    # definition time (important for django apps registry loading order).
    from apps.permissions.cache import get_user_version
    from apps.permissions.models import StoreMembership
    from apps.permissions.resolver import PermissionResolver

    # All active store memberships.
    memberships = list(
        StoreMembership.objects.filter(user=user, is_active=True)
        .select_related("store")
        .order_by("-joined_at")
    )
    store_ids = [str(m.store_id) for m in memberships]
    last_store = memberships[0].store if memberships else None

    permissions: list[str] = []
    features: list[str] = []
    if last_store is not None:
        # Aggregate permission codes for the most-recent store.
        # We use the resolver's private helper to avoid re-running the
        # cache layer (the token IS the cache for this request).
        try:
            grants, denies = PermissionResolver()._compute_grants_and_denies(
                user, last_store,
            )
            permissions = sorted(grants - denies)
        except Exception:
            permissions = []
        # Features for that store's plan.
        try:
            features = sorted(PermissionResolver()._load_features(user, last_store))
        except Exception:
            features = []

    return {
        "email": user.email,
        "is_superuser": bool(getattr(user, "is_superuser", False)),
        "stores": store_ids,
        "current_store_id": str(last_store.id) if last_store else "",
        "permissions": permissions,
        "features": features,
        "token_version": get_user_version(user.pk),
    }


class RBACTokenObtainPairSerializer(TokenObtainPairSerializer):
    """JWT serializer that embeds RBAC claims in the access token.

    Wire this in ``apps.accounts.urls_api`` by replacing the existing
    serializer_class::

        from apps.accounts.serializers_rbac import RBACTokenObtainPairSerializer
        class MyTokenView(TokenObtainPairView):
            serializer_class = RBACTokenObtainPairSerializer
    """

    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        claims = _collect_user_claims(user)
        for k, v in claims.items():
            token[k] = v
        return token

    def validate(self, attrs):
        data = super().validate(attrs)
        # Surface the RBAC claims in the response body as well, so the
        # frontend can stash them on initial login without parsing the JWT.
        claims = _collect_user_claims(self.user)
        data["rbac"] = claims
        return data
