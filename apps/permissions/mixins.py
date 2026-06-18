"""
CBV mixins for authorization.

- ``StoreContextMixin``       — set ``request.store`` from kwarg/header/session.
- ``PermissionRequiredMixin`` — gate a CBV by a permission code.
- ``FeatureRequiredMixin``   — gate a CBV by a plan feature.
- ``StoreAccessMixin``       — require an active store membership.
- ``StoreScopedQuerysetMixin`` — auto-filter a ViewSet queryset by store.
- ``HasObjectPermissionMixin`` — pair with DRF for object-level checks.
"""

from __future__ import annotations

import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template.loader import render_to_string

from .resolver import PermissionResolver


logger = logging.getLogger("apps.permissions")


# ---------------------------------------------------------------------------
# Store context resolution (for DRF CBVs)
# ---------------------------------------------------------------------------
class StoreContextMixin:
    """
    Resolve ``request.store`` in ``initial()`` (before DRF permission
    checks run). Resolution order: URL kwarg → header → session.

    Fail-closed when a store is required but unresolvable.

    Set ``store_kwarg`` (default ``"store_id"``), ``store_header``
    (default ``"X-Store-Id"``), ``store_session_key`` (default
    ``"current_store_id"``) and ``store_required`` (default ``True``).
    """

    store_kwarg: str = "store_id"
    store_header: str = "X-Store-Id"
    store_session_key: str = "current_store_id"
    store_required: bool = True

    def initial(self, request, *args, **kwargs):
        from .models import Store

        raw = kwargs.get(self.store_kwarg)
        if not raw:
            raw = request.headers.get(self.store_header)
        if not raw:
            raw = request.session.get(self.store_session_key)

        store = (
            Store.objects.filter(id=raw, is_deleted=False).first()
            if raw else None
        )
        request.store = store

        if store is None and self.store_required:
            logger.info(
                "rbac.store_ctx_missing view=%s path=%s",
                type(self).__name__, request.path,
            )
            # Defer the raise to permission checks so DRF returns a
            # structured 403 rather than a 500.
        super().initial(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Permission gating
# ---------------------------------------------------------------------------
class PermissionRequiredMixin(LoginRequiredMixin):
    """
    Gate a CBV by a permission code.

    Set ``permission_required = "orders.create"`` on the view.

    Set ``object_permission = True`` if the view looks up a single object
    via ``get_object()`` and you want the resolver to receive it for
    object-level checks (Layer 5).
    """

    permission_required: str | None = None
    object_permission: bool = False

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        store = getattr(request, "store", None)
        obj = None
        if self.object_permission and hasattr(self, "get_object"):
            try:
                obj = self.get_object()
            except Exception:
                obj = None
        ok = PermissionResolver().check(
            request.user, store, self.permission_required, obj=obj,
        )
        if not ok:
            logger.info(
                "rbac.denied view=%s user=%s code=%s",
                type(self).__name__, request.user.pk, self.permission_required,
            )
            return self._deny(request)
        return super().dispatch(request, *args, **kwargs)

    def _deny(self, request):
        if request.headers.get("HX-Request"):
            try:
                body = render_to_string("errors/_403_partial.html", request=request)
            except Exception:
                body = "Access denied."
            return HttpResponse(body, status=403)
        raise PermissionDenied


class FeatureRequiredMixin(LoginRequiredMixin):
    """Gate a CBV by a plan feature. Set ``required_feature = 'marketing_campaigns'`."""

    required_feature: str | None = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        store = getattr(request, "store", None)
        if not PermissionResolver().check_feature(request.user, store, self.required_feature):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class StoreAccessMixin(LoginRequiredMixin):
    """Require an active membership in the current store.

    Anonymous → login redirect.
    Authenticated but no active membership → 403 (not login redirect).
    """

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        store = getattr(request, "store", None)
        if not store:
            raise PermissionDenied
        from .models import StoreMembership

        if request.user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        if not StoreMembership.objects.filter(
            user=request.user, store=store, is_active=True,
        ).exists():
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)


class StoreScopedQuerysetMixin:
    """
    Auto-filter a ViewSet queryset to the current store.

    Requires the model to have a ``store`` FK. If no store is in the
    request, returns an empty queryset (deny-by-default).
    """

    def get_queryset(self):
        qs = super().get_queryset()
        store = getattr(self.request, "store", None)
        if store is None:
            return qs.none()
        return qs.filter(store=store)