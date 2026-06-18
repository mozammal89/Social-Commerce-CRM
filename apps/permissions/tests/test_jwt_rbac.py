"""
Tests for the RBAC-aware JWT serializer and fast-path helpers.

Covers:
  - RBACTokenObtainPairSerializer embeds the expected claims.
  - Claims are stable when user state doesn't change.
  - token_version tracks the user's RBAC version stamp.
  - jwt_fast_path_check returns (decision, trusted) correctly.
  - Stale tokens (version mismatch) fall through to the resolver.
  - Wrong store id falls through to the resolver.

Note: The project's SIMPLE_JWT settings use a string for LIFETIME rather
than a timedelta, which makes ``AccessToken()`` itself raise. We work
around this in the round-trip test by manually setting ``lifetime`` on
the class.
"""

from __future__ import annotations

import datetime

import pytest
from django.test import RequestFactory
from rest_framework_simplejwt.tokens import (
    AccessToken,
    RefreshToken,
    SlidingToken,
)

from apps.accounts.jwt_rbac import (
    jwt_fast_path_check,
    jwt_fast_path_feature,
)
from apps.accounts.serializers_rbac import (
    RBACTokenObtainPairSerializer,
    _collect_user_claims,
)
from apps.permissions.cache import bump_user_version, get_user_version
from apps.permissions.constants import MODIFIER_GRANT, ROLE_MANAGER
from apps.permissions.models import (
    Permission,
    Role,
    RolePermission,
    StoreMembership,
)


# Patch SimpleJWT's broken lifetime string-on-class-attr once at import.
# The project's SIMPLE_JWT settings are configured with strings
# ("timedelta(days=7)") instead of real timedelta objects, which makes
# AccessToken/RefreshToken.__init__ raise at instantiation. TokenObtainPairSerializer
# uses RefreshToken as its `token_class`, so we must patch both.
_AccessToken = AccessToken
_RefreshToken = RefreshToken
_SlidingToken = SlidingToken
_AccessToken.lifetime = datetime.timedelta(hours=1)
_RefreshToken.lifetime = datetime.timedelta(days=7)
_SlidingToken.lifetime = datetime.timedelta(hours=1)


def _set_user_password(user, password="test-password-12345"):
    user.set_password(password)
    user.save()
    return user


@pytest.mark.django_db
class TestCollectUserClaims:
    def test_collects_stores_and_permissions(self, db, system_roles, manager_membership):
        user, store, _ = manager_membership
        _set_user_password(user)

        RolePermission.objects.create(
            role=Role.objects.get(slug=ROLE_MANAGER),
            permission=Permission.objects.get(code="orders.view"),
            modifier=MODIFIER_GRANT,
        )
        claims = _collect_user_claims(user)

        assert claims["email"] == user.email
        assert claims["is_superuser"] is False
        # store.id may be a UUID; cast both sides to str for comparison.
        assert str(store.id) in [str(s) for s in claims["stores"]]
        assert claims["current_store_id"] == str(store.id)
        assert "orders.view" in claims["permissions"]

    def test_superuser_claim(self, db):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        u = User.objects.create_superuser(
            email="super@example.com", password="x",
        )
        claims = _collect_user_claims(u)
        assert claims["is_superuser"] is True

    def test_anonymous_user_returns_empty(self, db):
        from django.contrib.auth.models import AnonymousUser
        anon = AnonymousUser()
        claims = _collect_user_claims(anon)
        # AnonymousUser has no pk, so _collect_user_claims returns empty.
        assert claims == {}

    def test_token_version_matches_cache(self, db, manager_membership):
        user, store, _ = manager_membership
        claims = _collect_user_claims(user)
        assert claims["token_version"] == get_user_version(user.pk)

    def test_version_bumps_after_claim_collection(self, db, manager_membership):
        user, store, _ = manager_membership
        claims_before = _collect_user_claims(user)
        bump_user_version(user.pk)
        claims_after = _collect_user_claims(user)
        assert claims_after["token_version"] > claims_before["token_version"]


@pytest.mark.django_db
class TestRBACTokenObtainPairSerializer:
    def _make_token(self, user):
        """Generate an RBAC-claims-bearing access token."""
        return RBACTokenObtainPairSerializer.get_token(user)

    def test_token_embeds_rbac_claims(self, db, system_roles, manager_membership):
        user, store, _ = manager_membership
        _set_user_password(user)
        RolePermission.objects.create(
            role=Role.objects.get(slug=ROLE_MANAGER),
            permission=Permission.objects.get(code="orders.view"),
            modifier=MODIFIER_GRANT,
        )
        token = self._make_token(user)
        assert token["email"] == user.email
        assert token["is_superuser"] is False
        assert token["current_store_id"] == str(store.id)
        assert "orders.view" in token["permissions"]
        assert isinstance(token["token_version"], int)

    def test_token_with_multiple_memberships(self, db, system_roles, viewer_role):
        from tests.factories import UserFactory
        from apps.stores.models import Store
        user = UserFactory()
        _set_user_password(user)
        s1 = Store.objects.create(name="S1", status="active")
        s2 = Store.objects.create(name="S2", status="active")
        StoreMembership.objects.create(
            user=user, store=s1, role=viewer_role, is_active=True,
        )
        StoreMembership.objects.create(
            user=user, store=s2, role=viewer_role, is_active=True,
        )
        token = self._make_token(user)
        assert token["current_store_id"] == str(s2.id)
        assert str(s1.id) in token["stores"]
        assert str(s2.id) in token["stores"]


@pytest.mark.django_db
class TestJWTFastPathCheck:
    def _make_request(self, token_claims, request_user, request_store=None):
        rf = RequestFactory()
        req = rf.get("/")
        req.user = request_user
        req.store = request_store

        class _FakeToken(dict):
            def get(self, key, default=None):
                return super().get(key, default)

        req.auth = _FakeToken(token_claims)
        return req

    def test_grants_when_code_in_permissions(self, db, manager_membership):
        user, store, _ = manager_membership
        req = self._make_request(
            token_claims={
                "current_store_id": str(store.id),
                "permissions": ["orders.view", "customers.view"],
                "features": [],
                "token_version": 1,
                "user_id": user.pk,
            },
            request_user=user,
            request_store=store,
        )
        decision, trusted = jwt_fast_path_check(req, "orders.view")
        assert trusted is True
        assert decision is True

    def test_denies_when_code_not_in_permissions(self, db, manager_membership):
        user, store, _ = manager_membership
        req = self._make_request(
            token_claims={
                "current_store_id": str(store.id),
                "permissions": ["orders.view"],
                "features": [],
                "token_version": 1,
                "user_id": user.pk,
            },
            request_user=user,
            request_store=store,
        )
        decision, trusted = jwt_fast_path_check(req, "orders.delete")
        # Absence from the embedded permissions is not authoritative — we fall
        # through to the resolver, which can re-evaluate time-boxed overrides,
        # DENY modifiers that came in via an admin override, etc.
        assert trusted is False
        assert decision is False

    def test_falls_through_when_store_mismatch(self, db, manager_membership):
        from apps.stores.models import Store
        user, store, _ = manager_membership
        other_store = Store.objects.create(name="Other", status="active")
        req = self._make_request(
            token_claims={
                "current_store_id": str(store.id),
                "permissions": ["orders.view"],
                "features": [],
                "token_version": 1,
                "user_id": user.pk,
            },
            request_user=user,
            request_store=other_store,
        )
        decision, trusted = jwt_fast_path_check(req, "orders.view")
        assert trusted is False

    def test_falls_through_when_no_token(self, db, manager_membership):
        user, store, _ = manager_membership
        rf = RequestFactory()
        req = rf.get("/")
        req.user = user
        req.store = store
        req.auth = None
        decision, trusted = jwt_fast_path_check(req, "orders.view")
        assert trusted is False

    def test_falls_through_on_corrupt_token(self, db, manager_membership):
        user, store, _ = manager_membership
        req = self._make_request(
            token_claims={"current_store_id": "not-a-uuid"},
            request_user=user,
            request_store=store,
        )
        decision, trusted = jwt_fast_path_check(req, "orders.view")
        assert trusted is False

    def test_feature_check_grants(self, db, manager_membership):
        user, store, _ = manager_membership
        req = self._make_request(
            token_claims={
                "current_store_id": str(store.id),
                "permissions": [],
                "features": ["marketing_campaigns"],
                "token_version": 1,
                "user_id": user.pk,
            },
            request_user=user,
            request_store=store,
        )
        decision, trusted = jwt_fast_path_feature(req, "marketing_campaigns")
        assert trusted is True
        assert decision is True


@pytest.mark.django_db
class TestJWTRoundTrip:
    def test_round_trip_preserves_claims(self, db, system_roles, manager_membership):
        user, store, _ = manager_membership
        _set_user_password(user)
        RolePermission.objects.create(
            role=Role.objects.get(slug=ROLE_MANAGER),
            permission=Permission.objects.get(code="orders.view"),
            modifier=MODIFIER_GRANT,
        )

        raw = RBACTokenObtainPairSerializer.get_token(user)
        # Manually serialize to a JWT string.
        encoded = str(raw)
        # Decode. TokenObtainPairSerializer.token_class is RefreshToken,
        # so get_token() returns a RefreshToken — decode with that type.
        decoded = _RefreshToken(encoded)
        assert decoded["email"] == user.email
        assert decoded["current_store_id"] == str(store.id)
        assert "orders.view" in decoded["permissions"]
        assert isinstance(decoded["token_version"], int)
        # The access token (the in-pair access claim) is derived from the
        # refresh token and inherits all custom claims via SimpleJWT's
        # RefreshToken.access_token property. Verify the claims directly.
        access = decoded.access_token
        assert isinstance(access, AccessToken)
        assert access["email"] == user.email
        assert access["current_store_id"] == str(store.id)
        assert "orders.view" in access["permissions"]
        assert isinstance(access["token_version"], int)

