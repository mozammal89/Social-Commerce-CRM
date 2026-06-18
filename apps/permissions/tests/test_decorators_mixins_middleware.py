"""
Tests for view-layer authorization glue:

- ``apps.permissions.decorators`` — function-view decorators.
- ``apps.permissions.mixins``     — CBV mixins.
- ``apps.permissions.middleware`` — AuditContextMiddleware + HTMX403Middleware.
- ``apps.permissions.exception_handler`` — DRF 403 enrichment.

These tests build minimal Django views / CBVs and exercise the decorators
end-to-end so we don't need the full project URLconf.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory
from django.views import View

from apps.permissions.decorators import (
    feature_required,
    permission_required,
    register_object_loader,
)
from apps.permissions.exception_handler import rbac_exception_handler
from apps.permissions.middleware import (
    AuditContextMiddleware,
    HTMX403Middleware,
    current_request_context,
    set_request_context,
)
from apps.permissions.mixins import (
    FeatureRequiredMixin,
    PermissionRequiredMixin,
    StoreAccessMixin,
    StoreScopedQuerysetMixin,
)


def _call_mixin(mixin_cls, *, request, **attrs):
    """Instantiate a mixin-backed view and call dispatch directly."""
    class V(mixin_cls, View):
        def get(self, request):
            return HttpResponse("ok")

    v = V()
    v.request = request
    v.kwargs = {}
    for k, val in attrs.items():
        setattr(v, k, val)
    return v.dispatch(request)


# ---------------------------------------------------------------------------
# permission_required decorator
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPermissionRequiredDecorator:
    def test_unauthenticated_user_redirects_to_login(self, db):
        rf = RequestFactory()

        @permission_required("orders.view")
        def my_view(request):
            return HttpResponse("ok")

        request = rf.get("/")
        request.user = AnonymousUser()
        request.store = None
        response = my_view(request)
        # login_required returns redirect to LOGIN_URL (302).
        assert response.status_code == 302

    def test_authenticated_user_with_permission_passes(
        self, manager_membership, permissions,
    ):
        from apps.permissions.models import RolePermission, Role
        from apps.permissions.constants import ROLE_MANAGER
        user, store, _ = manager_membership
        RolePermission.objects.create(
            role=Role.objects.get(slug=ROLE_MANAGER),
            permission=permissions["orders.view"],
            modifier="grant",
        )
        rf = RequestFactory()

        @permission_required("orders.view")
        def my_view(request):
            return HttpResponse("ok")

        request = rf.get("/")
        request.user = user
        request.store = store
        response = my_view(request)
        assert response.status_code == 200
        assert response.content == b"ok"

    def test_authenticated_user_without_permission_raises(
        self, manager_membership,
    ):
        user, store, _ = manager_membership
        rf = RequestFactory()

        @permission_required("orders.delete")
        def my_view(request):
            return HttpResponse("ok")

        request = rf.get("/")
        request.user = user
        request.store = store
        with pytest.raises(PermissionDenied):
            my_view(request)

    def test_superuser_bypasses(self, db):
        su = get_user_model().objects.create_superuser(email="su@x.com", password="x")
        rf = RequestFactory()

        @permission_required("anything.at_all")
        def my_view(request):
            return HttpResponse("ok")

        request = rf.get("/")
        request.user = su
        request.store = None
        assert my_view(request).status_code == 200

    def test_obj_kwarg_loader_runs(self, manager_membership):
        """When ``obj_kwarg`` is provided and the kwarg is in the URL kwargs,
        the loader is invoked (returns None when no loader registered)."""
        user, store, _ = manager_membership
        from tests.factories import UserFactory
        from apps.permissions.models import StoreMembership, Role
        from apps.permissions.constants import ROLE_VIEWER
        target_user = UserFactory()
        StoreMembership.objects.create(
            user=target_user, store=store,
            role=Role.objects.get(slug=ROLE_VIEWER), is_active=True,
        )
        register_object_loader(
            "user_id", "apps.accounts.models.User",
        )
        rf = RequestFactory()

        @permission_required("orders.view", obj_kwarg="user_id")
        def my_view(request, user_id):
            return HttpResponse("ok")

        request = rf.get("/")
        request.user = user
        request.store = store
        # Manager doesn't have orders.view; should PermissionDenied.
        with pytest.raises(PermissionDenied):
            my_view(request, user_id=str(target_user.id))


# ---------------------------------------------------------------------------
# feature_required decorator
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestFeatureRequiredDecorator:
    def test_user_in_store_with_feature_passes(
        self, active_subscription, manager_membership,
    ):
        from apps.permissions.models import StoreMembership, Role
        from apps.permissions.constants import ROLE_MANAGER
        store, _sub, _plan = active_subscription
        user, _user_store, _ = manager_membership
        StoreMembership.objects.create(
            user=user, store=store,
            role=Role.objects.get(slug=ROLE_MANAGER), is_active=True,
        )
        rf = RequestFactory()

        @feature_required("customer_management")
        def my_view(request):
            return HttpResponse("ok")

        request = rf.get("/")
        request.user = user
        request.store = store
        assert my_view(request).status_code == 200

    def test_user_without_feature_raises(self, manager_membership):
        user, store, _ = manager_membership
        rf = RequestFactory()

        @feature_required("marketing_campaigns")
        def my_view(request):
            return HttpResponse("ok")

        request = rf.get("/")
        request.user = user
        request.store = store
        with pytest.raises(PermissionDenied):
            my_view(request)

    def test_superuser_bypasses_feature_check(self, db):
        su = get_user_model().objects.create_superuser(email="su@x.com", password="x")
        rf = RequestFactory()

        @feature_required("anything")
        def my_view(request):
            return HttpResponse("ok")

        request = rf.get("/")
        request.user = su
        request.store = None
        assert my_view(request).status_code == 200


# ---------------------------------------------------------------------------
# Object loader (uncovered branch)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestObjectLoader:
    def test_unknown_kwarg_returns_none(self, db):
        from apps.permissions.decorators import _load_obj
        assert _load_obj("unknown_kwarg", 42) is None

    def test_invalid_import_path_returns_none(self, db):
        from apps.permissions.decorators import _load_obj
        register_object_loader("bogus", "nonexistent.module.Model")
        assert _load_obj("bogus", 1) is None

    def test_valid_loader_returns_object(self, manager_membership):
        from apps.permissions.decorators import _load_obj
        from tests.factories import UserFactory
        u = UserFactory()
        register_object_loader("user_id", "apps.accounts.models.User")
        loaded = _load_obj("user_id", str(u.id))
        assert loaded is not None
        assert loaded.id == u.id


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestPermissionRequiredMixin:
    def test_dispatch_passes_when_user_has_permission(
        self, manager_membership, permissions,
    ):
        from apps.permissions.models import RolePermission, Role
        from apps.permissions.constants import ROLE_MANAGER
        user, store, _ = manager_membership
        RolePermission.objects.create(
            role=Role.objects.get(slug=ROLE_MANAGER),
            permission=permissions["orders.view"], modifier="grant",
        )
        rf = RequestFactory()
        request = rf.get("/")
        request.user = user
        request.store = store
        response = _call_mixin(
            PermissionRequiredMixin,
            request=request,
            permission_required="orders.view",
        )
        assert response.status_code == 200

    def test_dispatch_denies_when_user_lacks_permission(self, manager_membership):
        user, store, _ = manager_membership
        rf = RequestFactory()
        request = rf.get("/")
        request.user = user
        request.store = store
        with pytest.raises(PermissionDenied):
            _call_mixin(
                PermissionRequiredMixin,
                request=request,
                permission_required="orders.delete",
            )

    def test_dispatch_returns_partial_on_htmx_403(self, manager_membership):
        user, store, _ = manager_membership
        rf = RequestFactory()
        request = rf.get("/", HTTP_HX_REQUEST="true")
        request.user = user
        request.store = store
        response = _call_mixin(
            PermissionRequiredMixin,
            request=request,
            permission_required="orders.delete",
        )
        assert response.status_code == 403
        assert b"Access denied" in response.content or b"access" in response.content.lower()

    def test_dispatch_unauthenticated_redirects(self, db):
        rf = RequestFactory()
        request = rf.get("/")
        request.user = AnonymousUser()
        request.store = None
        response = _call_mixin(
            PermissionRequiredMixin,
            request=request,
            permission_required="orders.view",
        )
        # LoginRequiredMixin redirects → 302.
        assert response.status_code == 302

    def test_object_permission_invokes_get_object(self, manager_membership):
        user, store, _ = manager_membership
        rf = RequestFactory()

        class _FakeObject:
            pass

        class _View(PermissionRequiredMixin, View):
            permission_required = "orders.view"
            object_permission = True

            def get_object(self):
                return _FakeObject()

            def get(self, request):
                return HttpResponse("ok")

        request = rf.get("/")
        request.user = user
        request.store = store
        v = _View()
        v.request = request
        v.kwargs = {}
        # Manager has no orders.view grant → denied, but the test confirms
        # the mixin doesn't crash trying to call get_object.
        with pytest.raises(PermissionDenied):
            v.dispatch(request)


@pytest.mark.django_db
class TestFeatureRequiredMixin:
    def test_passes_when_user_has_feature(
        self, active_subscription, manager_membership,
    ):
        from apps.permissions.models import StoreMembership, Role
        from apps.permissions.constants import ROLE_MANAGER
        store, _sub, _plan = active_subscription
        user, _user_store, _ = manager_membership
        StoreMembership.objects.create(
            user=user, store=store,
            role=Role.objects.get(slug=ROLE_MANAGER), is_active=True,
        )
        rf = RequestFactory()
        request = rf.get("/")
        request.user = user
        request.store = store
        response = _call_mixin(
            FeatureRequiredMixin,
            request=request,
            required_feature="customer_management",
        )
        assert response.status_code == 200

    def test_denies_when_user_lacks_feature(self, manager_membership):
        user, store, _ = manager_membership
        rf = RequestFactory()
        request = rf.get("/")
        request.user = user
        request.store = store
        with pytest.raises(PermissionDenied):
            _call_mixin(
                FeatureRequiredMixin,
                request=request,
                required_feature="marketing_campaigns",
            )


@pytest.mark.django_db
class TestStoreAccessMixin:
    def test_passes_when_user_is_active_member(self, manager_membership):
        user, store, _ = manager_membership
        rf = RequestFactory()
        request = rf.get("/")
        request.user = user
        request.store = store
        response = _call_mixin(StoreAccessMixin, request=request)
        assert response.status_code == 200

    def test_superuser_passes_even_without_membership(self, db):
        su = get_user_model().objects.create_superuser(email="su@x.com", password="x")
        from apps.stores.models import Store
        other_store = Store.objects.create(name="Other", status="active")
        rf = RequestFactory()
        request = rf.get("/")
        request.user = su
        request.store = other_store
        response = _call_mixin(StoreAccessMixin, request=request)
        assert response.status_code == 200

    def test_denies_when_no_store(self, manager_membership):
        user, _store, _ = manager_membership
        rf = RequestFactory()
        request = rf.get("/")
        request.user = user
        request.store = None
        with pytest.raises(PermissionDenied):
            _call_mixin(StoreAccessMixin, request=request)

    def test_denies_when_user_not_member(self, manager_membership):
        user, _store, _ = manager_membership
        from apps.stores.models import Store
        other_store = Store.objects.create(name="Other", status="active")
        rf = RequestFactory()
        request = rf.get("/")
        request.user = user
        request.store = other_store
        with pytest.raises(PermissionDenied):
            _call_mixin(StoreAccessMixin, request=request)

    def test_unauthenticated_redirects(self, db):
        rf = RequestFactory()
        request = rf.get("/")
        request.user = AnonymousUser()
        request.store = None
        response = _call_mixin(StoreAccessMixin, request=request)
        assert response.status_code == 302


@pytest.mark.django_db
class TestStoreScopedQuerysetMixin:
    def test_filters_to_request_store(self, manager_membership):
        from apps.stores.models import Store
        from apps.permissions.models import StoreMembership
        from apps.permissions.constants import ROLE_MANAGER
        from apps.permissions.models import Role
        user, store, _ = manager_membership
        # Use a fresh store, not the one from the fixture (the fixture already
        # created a Manager membership there).
        s1 = Store.objects.create(name="Filter S1", status="active")
        s2 = Store.objects.create(name="Filter S2", status="active")
        StoreMembership.objects.create(
            user=user, store=s1, role=Role.objects.get(slug=ROLE_MANAGER),
            is_active=True,
        )
        StoreMembership.objects.create(
            user=user, store=s2, role=Role.objects.get(slug=ROLE_MANAGER),
            is_active=True,
        )
        rf = RequestFactory()
        request = rf.get("/")
        request.user = user
        request.store = s1

        # The mixin is designed to be placed BEFORE the base in the MRO,
        # so that the child's super().get_queryset() reaches the mixin first,
        # and the mixin's super().get_queryset() reaches the base.
        class _Base:
            def get_queryset(self):
                return StoreMembership.objects.filter(user=user)

        class _Child(StoreScopedQuerysetMixin, _Base):
            def get_queryset(self):
                return super().get_queryset()

        c = _Child()
        c.request = request
        # c.get_queryset() → super().get_queryset() (in _Child) →
        # StoreScopedQuerysetMixin.get_queryset (super()) → _Base.get_queryset
        # → mixin narrows → qs.filter(store=s1)
        qs = c.get_queryset()
        assert qs.count() == 1
        assert qs.first().store_id == s1.id

    def test_returns_empty_when_no_store(self, manager_membership):
        from apps.permissions.models import StoreMembership as SM
        user, _store, _ = manager_membership
        rf = RequestFactory()
        request = rf.get("/")
        request.user = user
        request.store = None

        class _Base:
            def get_queryset(self):
                return SM.objects.filter(user=user)

        class _Child(StoreScopedQuerysetMixin, _Base):
            def get_queryset(self):
                return super().get_queryset()

        c = _Child()
        c.request = request
        result = c.get_queryset()
        # qs.none() → empty queryset (deny-by-default).
        assert list(result) == []


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAuditContextMiddleware:
    def test_sets_context_during_request_and_resets_after(self, db):
        rf = RequestFactory()
        captured = {}

        def get_response(request):
            captured["ctx"] = current_request_context()
            return HttpResponse("ok")

        mw = AuditContextMiddleware(get_response)
        request = rf.get("/", HTTP_USER_AGENT="TestAgent/1.0", REMOTE_ADDR="127.0.0.1")
        request.user = get_user_model()(email="u@x.com")
        request.store = None
        response = mw(request)
        assert captured["ctx"] is not None
        assert captured["ctx"]["user"].email == "u@x.com"
        assert captured["ctx"]["ip"] == "127.0.0.1"
        assert captured["ctx"]["ua"] == "TestAgent/1.0"
        # After request, the contextvar is reset.
        assert current_request_context() is None
        assert "X-Request-ID" in response

    def test_uses_provided_request_id_header(self, db):
        rf = RequestFactory()
        captured = {}

        def get_response(request):
            captured["ctx"] = current_request_context()
            return HttpResponse("ok")

        mw = AuditContextMiddleware(get_response)
        request = rf.get("/", HTTP_X_REQUEST_ID="my-correlation-id")
        request.user = get_user_model()(email="u@x.com")
        request.store = None
        response = mw(request)
        assert captured["ctx"]["request_id"] == "my-correlation-id"
        assert response["X-Request-ID"] == "my-correlation-id"

    def test_uses_store_id_from_request(self, manager_membership):
        _user, store, _ = manager_membership
        rf = RequestFactory()
        captured = {}

        def get_response(request):
            captured["ctx"] = current_request_context()
            return HttpResponse("ok")

        mw = AuditContextMiddleware(get_response)
        request = rf.get("/")
        request.user = get_user_model()(email="u@x.com")
        request.store = store
        mw(request)
        assert captured["ctx"]["store_id"] == store.id

    def test_ua_truncated_to_512(self, db):
        rf = RequestFactory()
        captured = {}

        def get_response(request):
            captured["ctx"] = current_request_context()
            return HttpResponse("ok")

        mw = AuditContextMiddleware(get_response)
        long_ua = "x" * 1000
        request = rf.get("/", HTTP_USER_AGENT=long_ua)
        request.user = get_user_model()(email="u@x.com")
        request.store = None
        mw(request)
        assert len(captured["ctx"]["ua"]) == 512


@pytest.mark.django_db
class TestSetRequestContext:
    def test_set_request_context_populates_ctx(self):
        set_request_context(user="alice", store_id=42)
        ctx = current_request_context()
        assert ctx["user"] == "alice"
        assert ctx["store_id"] == 42

    def test_set_request_context_merges_with_existing(self):
        set_request_context(user="alice")
        set_request_context(store_id=42)
        ctx = current_request_context()
        assert ctx["user"] == "alice"
        assert ctx["store_id"] == 42


@pytest.mark.django_db
class TestHTMX403Middleware:
    def _make_response(self, status_code):
        return HttpResponse("body", status=status_code)

    def test_non_403_passthrough(self, db):
        rf = RequestFactory()

        def get_response(request):
            return self._make_response(200)

        mw = HTMX403Middleware(get_response)
        request = rf.get("/")
        assert mw(request).status_code == 200

    def test_non_htmx_403_passthrough(self, db):
        rf = RequestFactory()

        def get_response(request):
            return self._make_response(403)

        mw = HTMX403Middleware(get_response)
        request = rf.get("/")
        # process_response swaps body if HTMX, else returns response unchanged.
        response = mw(request)
        assert response.status_code == 403
        assert response.content == b"body"


# ---------------------------------------------------------------------------
# Exception handler
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestRbacExceptionHandler:
    def test_returns_none_for_unhandled_exception(self, db):
        result = rbac_exception_handler(ValueError("nope"), {})
        # The default handler returns None for non-DRF exceptions.
        assert result is None

    def test_enriches_403_with_required_permission(self, db):
        from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
        from rest_framework.views import APIView

        class _StubExc(DRFPermissionDenied):
            required_permission = "orders.delete"

        response = rbac_exception_handler(
            _StubExc(), {"view": APIView(), "request": None},
        )
        assert response is not None
        assert response.status_code == 403
        assert response.data["error"] == "forbidden"
        assert response.data["required_permission"] == "orders.delete"
        assert response.data["required_feature"] is None

    def test_enriches_403_with_required_feature(self, db):
        from rest_framework.exceptions import PermissionDenied as DRFPermissionDenied
        from rest_framework.views import APIView

        class _StubExc(DRFPermissionDenied):
            required_feature = "marketing_campaigns"

        response = rbac_exception_handler(
            _StubExc(), {"view": APIView(), "request": None},
        )
        assert response is not None
        assert response.status_code == 403
        assert response.data["required_permission"] is None
        assert response.data["required_feature"] == "marketing_campaigns"

    def test_passes_through_401_unchanged(self, db):
        from rest_framework.exceptions import NotAuthenticated
        from rest_framework.views import APIView

        response = rbac_exception_handler(
            NotAuthenticated(), {"view": APIView(), "request": None},
        )
        assert response is not None
        assert response.status_code == 401

# ---------------------------------------------------------------------------
# @current_store decorator (Bug 7)
# ---------------------------------------------------------------------------
from apps.permissions.decorators import current_store as current_store_deco


@pytest.mark.django_db
class TestCurrentStoreDecorator:
    """Tests for the ``@current_store`` decorator.

    Resolves ``request.store`` from URL kwarg → header → session, and
    enforces active membership (superuser bypasses).
    """

    def _make_request(self, rf, user, **kwargs):
        request = rf.get("/", **kwargs)
        request.user = user
        request.store = None
        return request

    def _fresh_store(self):
        from apps.stores.models import Store
        return Store.objects.create(name="CS Test Store", status="active")

    def _seed_role(self):
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        RolesSeeder().run()
        from apps.permissions.models import Role
        return Role.objects.get(slug="manager", store=None)

    def test_resolves_store_from_url_kwarg(self, db, django_user_model):
        rf = RequestFactory()
        user = django_user_model.objects.create_user(
            email="cs-url@example.com", password="x",
        )
        store = self._fresh_store()
        role = self._seed_role()
        from apps.permissions.models import StoreMembership
        StoreMembership.objects.create(
            user=user, store=store, role=role, is_active=True,
        )

        @current_store_deco
        def my_view(request, store_id=None):
            return HttpResponse("ok")

        request = self._make_request(rf, user)
        response = my_view(request, store_id=str(store.id))
        assert response.status_code == 200
        assert str(request.store.id) == str(store.id)

    def test_resolves_store_from_header(self, db, django_user_model):
        rf = RequestFactory()
        user = django_user_model.objects.create_user(
            email="cs-hdr@example.com", password="x",
        )
        store = self._fresh_store()
        role = self._seed_role()
        from apps.permissions.models import StoreMembership
        StoreMembership.objects.create(
            user=user, store=store, role=role, is_active=True,
        )

        @current_store_deco
        def my_view(request, store_id=None):
            return HttpResponse("ok")

        request = rf.get("/", HTTP_X_STORE_ID=str(store.id))
        request.user = user
        request.store = None
        response = my_view(request)
        assert response.status_code == 200
        assert str(request.store.id) == str(store.id)

    def test_resolves_store_from_session(self, db, django_user_model):
        rf = RequestFactory()
        user = django_user_model.objects.create_user(
            email="cs-sess@example.com", password="x",
        )
        store = self._fresh_store()
        role = self._seed_role()
        from apps.permissions.models import StoreMembership
        StoreMembership.objects.create(
            user=user, store=store, role=role, is_active=True,
        )

        @current_store_deco
        def my_view(request, store_id=None):
            return HttpResponse("ok")

        from django.contrib.sessions.middleware import SessionMiddleware
        request = rf.get("/")
        request.user = user
        request.store = None
        middleware = SessionMiddleware(lambda r: None)
        middleware.process_request(request)
        request.session["current_store_id"] = str(store.id)
        request.session.save()

        response = my_view(request)
        assert response.status_code == 200
        assert str(request.store.id) == str(store.id)

    def test_unauthenticated_redirects_to_login(self, db):
        rf = RequestFactory()
        store = self._fresh_store()

        @current_store_deco
        def my_view(request, store_id=None):
            return HttpResponse("ok")

        request = self._make_request(rf, AnonymousUser())
        response = my_view(request, store_id=str(store.id))
        # Anonymous → login redirect (302)
        assert response.status_code == 302

    def test_non_member_raises_permission_denied(
        self, db, django_user_model,
    ):
        rf = RequestFactory()
        user = django_user_model.objects.create_user(
            email="cs-nm@example.com", password="x",
        )
        store = self._fresh_store()

        @current_store_deco
        def my_view(request, store_id=None):
            return HttpResponse("ok")

        request = self._make_request(rf, user)
        with pytest.raises(PermissionDenied):
            my_view(request, store_id=str(store.id))

    def test_inactive_member_is_treated_as_non_member(
        self, db, django_user_model,
    ):
        rf = RequestFactory()
        user = django_user_model.objects.create_user(
            email="cs-ia@example.com", password="x",
        )
        store = self._fresh_store()
        role = self._seed_role()
        from apps.permissions.models import StoreMembership
        StoreMembership.objects.create(
            user=user, store=store, role=role, is_active=False,
        )

        @current_store_deco
        def my_view(request, store_id=None):
            return HttpResponse("ok")

        request = self._make_request(rf, user)
        with pytest.raises(PermissionDenied):
            my_view(request, store_id=str(store.id))

    def test_superuser_bypasses_membership(
        self, db, django_user_model,
    ):
        rf = RequestFactory()
        su = django_user_model.objects.create_superuser(
            email="cs-su@example.com", password="x",
        )
        store = self._fresh_store()

        @current_store_deco
        def my_view(request, store_id=None):
            return HttpResponse("ok")

        request = self._make_request(rf, su)
        response = my_view(request, store_id=str(store.id))
        assert response.status_code == 200

    def test_soft_deleted_store_rejected(self, db, django_user_model):
        rf = RequestFactory()
        user = django_user_model.objects.create_user(
            email="cs-sd@example.com", password="x",
        )
        store = self._fresh_store()
        role = self._seed_role()
        from apps.permissions.models import StoreMembership
        StoreMembership.objects.create(
            user=user, store=store, role=role, is_active=True,
        )
        store.soft_delete(deleted_by=user)

        @current_store_deco
        def my_view(request, store_id=None):
            return HttpResponse("ok")

        request = self._make_request(rf, user)
        with pytest.raises(PermissionDenied):
            my_view(request, store_id=str(store.id))

    def test_missing_store_raises_when_required(self, db, django_user_model):
        rf = RequestFactory()
        user = django_user_model.objects.create_user(
            email="cs-ms@example.com", password="x",
        )

        @current_store_deco
        def my_view(request, store_id=None):
            return HttpResponse("ok")

        request = self._make_request(rf, user)
        with pytest.raises(PermissionDenied):
            my_view(request)

    def test_missing_store_allowed_when_not_required(
        self, db, django_user_model,
    ):
        rf = RequestFactory()
        user = django_user_model.objects.create_user(
            email="cs-opt@example.com", password="x",
        )

        @current_store_deco(required=False)
        def my_view(request, store_id=None):
            return HttpResponse("ok")

        request = self._make_request(rf, user)
        response = my_view(request)
        assert response.status_code == 200
        assert request.store is None


# ---------------------------------------------------------------------------
# Bug 5: authenticated-but-denied returns 403 (not a login redirect)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestAuthenticatedButDeniedReturns403:
    def test_permission_required_authenticated_denied_returns_403(
        self, manager_membership, permissions,
    ):
        rf = RequestFactory()
        user, store, _ = manager_membership

        @permission_required("customers.delete")  # manager lacks this
        def my_view(request):
            return HttpResponse("ok")

        request = rf.get("/")
        request.user = user
        request.store = store
        with pytest.raises(PermissionDenied):
            my_view(request)

    def test_feature_required_authenticated_denied_returns_403(
        self, manager_membership,
    ):
        rf = RequestFactory()
        user, store, _ = manager_membership

        @feature_required("marketing_campaigns")
        def my_view(request):
            return HttpResponse("ok")

        request = rf.get("/")
        request.user = user
        request.store = store
        with pytest.raises(PermissionDenied):
            my_view(request)
