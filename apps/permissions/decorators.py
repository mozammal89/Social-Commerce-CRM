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
"""

from __future__ import annotations

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .resolver import PermissionResolver


_resolver = PermissionResolver()


def permission_required(code: str, *, obj_kwarg: str | None = None):
    """
    Require a permission code. Returns 403 on failure.

    If ``obj_kwarg`` is provided, the decorator will load the object
    from the URL kwarg of that name and pass it to the resolver as
    Layer 5 (object-level) context. The view still receives the kwarg
    unchanged.
    """
    def deco(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            store = getattr(request, "store", None)
            obj = None
            if obj_kwarg and obj_kwarg in kwargs:
                obj = _load_obj(obj_kwarg, kwargs[obj_kwarg])
            if not _resolver.check(request.user, store, code, obj=obj):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return deco


def feature_required(feature_code: str):
    """Require that the user's store plan has the feature."""
    def deco(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            store = getattr(request, "store", None)
            if not _resolver.check_feature(request.user, store, feature_code):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapper

    return deco


# ---------------------------------------------------------------------------
# Object loading — pluggable map. Add entries when apps define new models.
# ---------------------------------------------------------------------------
_OBJECT_LOADERS = {
    # 'order_id': 'apps.orders.models.Order',
    # 'customer_id': 'apps.customers.models.Customer',
}


def register_object_loader(kwarg: str, import_path: str) -> None:
    """Allow apps to register how to load an obj from a URL kwarg."""
    _OBJECT_LOADERS[kwarg] = import_path


def _load_obj(kwarg: str, value):
    import_path = _OBJECT_LOADERS.get(kwarg)
    if not import_path:
        return None
    try:
        module_path, _, class_name = import_path.rpartition(".")
        import importlib
        module = importlib.import_module(module_path)
        model = getattr(module, class_name)
        return model.objects.filter(pk=value).first()
    except Exception:
        return None