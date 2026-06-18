"""
Function-view authorization decorators.

Usage:

    @permission_required("orders.create")
    def create_order(request):
        ...

    @permission_required("orders.view", obj_kwarg="order_id")
    def order_detail(request, order_id):
        order = get_object_or_404(Order, pk=order_id)
        ...

    @feature_required("marketing_campaigns")
    def campaign_list(request):
        ...

    @current_store
    def store_dashboard(request):
        # request.store is now set
        ...
"""

from __future__ import annotations

import logging
from functools import wraps

from django.conf import settings as dj_settings
from django.core.exceptions import PermissionDenied

from .resolver import PermissionResolver


logger = logging.getLogger("apps.permissions")

_resolver = PermissionResolver()


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def _enforce_login(request, view_func):
    """
    Return ``None`` if the user is allowed through, or an ``HttpResponse``
    to short-circuit (the standard login redirect for anonymous users).

    The wrapped view receives an authenticated user; authenticated-but-
    denied is handled by the permission check itself (returns 403).
    """
    if request.user.is_authenticated:
        return None
    # Anonymous → behave like @login_required would.
    from django.contrib.auth.decorators import login_required
    # Use Django's login_required as a function call (not a decorator).
    inner = login_required(view_func)
    # The inner wrapper handles the redirect and returns an HttpResponse
    # when unauthenticated, or the view result when authed. We invoke it
    # with the request and inspect what comes back; if the request is
    # authenticated we don't get back the view result here because the
    # caller has already passed the check. So just return a sentinel to
    # tell the caller to redirect via the standard mechanism.
    return "LOGIN_REQUIRED"


# ---------------------------------------------------------------------------
# Auth + Permission decorator
# ---------------------------------------------------------------------------
def _authenticate(request):
    """Resolve the login redirect target URL from settings."""
    from django.contrib.auth.views import redirect_to_login
    return redirect_to_login(
        request.get_full_path(),
        login_url=getattr(dj_settings, "LOGIN_URL", "/accounts/login/"),
    )


def permission_required(code: str, *, obj_kwarg: str | None = None):
    """
    Require a permission code. Returns 403 on failure.

    Behavior:
      * Anonymous user → redirect to LOGIN_URL (with ``next``).
      * Authenticated user with the permission → view runs.
      * Authenticated user without the permission → 403 (not a redirect).

    If ``obj_kwarg`` is provided, the decorator will load the object
    from the URL kwarg of that name and pass it to the resolver as
    Layer 5 (object-level) context.
    """
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return _authenticate(request)
            store = getattr(request, "store", None)
            obj = None
            if obj_kwarg and obj_kwarg in kwargs:
                obj = _load_obj(obj_kwarg, kwargs[obj_kwarg])
            if not _resolver.check(request.user, store, code, obj=obj):
                _log_denied(request, code, view)
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return deco


def feature_required(feature_code: str):
    """Require that the user's store plan has the feature.

    Anonymous → login redirect.
    Authenticated but no feature → 403.
    """
    def deco(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return _authenticate(request)
            store = getattr(request, "store", None)
            if not _resolver.check_feature(request.user, store, feature_code):
                _log_denied(request, feature_code, view)
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return deco


# ---------------------------------------------------------------------------
# @current_store — resolve and validate the current store on the request
# ---------------------------------------------------------------------------
def current_store(
    view=None,
    *,
    store_kwarg: str = "store_id",
    session_key: str = "current_store_id",
    header: str = "X-Store-Id",
    required: bool = True,
):
    """
    Per-view store resolver + membership guard.

    Resolution order: URL kwarg → request header → session.

    The resolved store is stashed on ``request.store``. Membership is
    enforced (superuser bypasses) unless the view explicitly opts out
    via ``required=False``.

    Usage::

        @current_store
        def store_dashboard(request, store_id=None):
            # request.store is set; user is a member
            ...

        @current_store(store_kwarg="uuid", required=False)
        def store_preview(request, uuid):
            # request.store is set if resolvable; no membership check
            ...
    """
    def _wrap(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            store = _resolve_store(request, kwargs, store_kwarg, session_key, header)
            if store is None:
                if not required:
                    request.store = None
                    return view(request, *args, **kwargs)
                _log_denied(request, "store_context", view, reason="missing")
                raise PermissionDenied("Store context required.")

            request.store = store
            # Membership check (superuser bypasses)
            if not request.user.is_authenticated:
                return _authenticate(request)
            if not request.user.is_superuser and not _user_is_member(request.user, store):
                _log_denied(request, "store_membership", view, reason="non_member")
                raise PermissionDenied("You are not a member of this store.")
            return view(request, *args, **kwargs)

        return wrapper

    if view is not None and callable(view):
        # Bare ``@current_store`` (no parens)
        return _wrap(view)
    # Parameterised ``@current_store(...)`` (with parens)
    return _wrap


def _resolve_store(request, kwargs, store_kwarg, session_key, header):
    """Resolution order: URL kwarg → header → session."""
    from apps.stores.models import Store

    # 1. URL kwarg
    raw = kwargs.get(store_kwarg)
    # 2. Header
    if not raw:
        raw = request.headers.get(header)
    # 3. Session (defensive: RequestFactory doesn't add session by default)
    if not raw:
        session = getattr(request, "session", None)
        if session is not None:
            try:
                raw = session.get(session_key)
            except Exception:
                raw = None

    if not raw:
        return None
    return Store.objects.filter(id=raw, is_deleted=False).first()


def _user_is_member(user, store) -> bool:
    from .models import StoreMembership
    return StoreMembership.objects.filter(
        user=user, store=store, is_active=True,
    ).exists()


def _log_denied(request, code, view, *, reason: str | None = None) -> None:
    """Log a denied access attempt at INFO level for security audits."""
    try:
        user_repr = (
            f"user={request.user.pk}({request.user.is_superuser and 'su' or 'reg'})"
            if request.user.is_authenticated else "user=anon"
        )
    except Exception:
        user_repr = "user=?"
    view_name = getattr(view, "__qualname__", None) or getattr(view, "__name__", repr(view))
    extra = f" reason={reason}" if reason else ""
    logger.info(
        "rbac.denied %s code=%s view=%s path=%s ip=%s%s",
        user_repr, code, view_name,
        getattr(request, "path", "?"),
        request.META.get("REMOTE_ADDR", "?"),
        extra,
    )


# ---------------------------------------------------------------------------
# Object loading — pluggable map. Apps register loaders in apps.py::ready().
# ---------------------------------------------------------------------------
_OBJECT_LOADERS: dict[str, str] = {
    # Populated by apps.orders.apps, apps.customers.apps, etc.
}


def register_object_loader(kwarg: str, import_path: str) -> None:
    """Allow apps to register how to load an obj from a URL kwarg."""
    _OBJECT_LOADERS[kwarg] = import_path


def _load_obj(kwarg: str, value):
    import_path = _OBJECT_LOADERS.get(kwarg)
    if not import_path:
        return None
    try:
        import importlib
        module_path, _, class_name = import_path.rpartition(".")
        module = importlib.import_module(module_path)
        model = getattr(module, class_name)
        return model.objects.filter(pk=value).first()
    except Exception:
        return None
