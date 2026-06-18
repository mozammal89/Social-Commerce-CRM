"""
Template-based views for the dashboard.

This module is the canonical demonstration of the RBAC feature:

* Superusers (``is_superuser=True``) bypass every permission check
  via ``PermissionResolver``'s built-in superuser short-circuit.
* Regular users see only the stores they have an **active**
  ``StoreMembership`` for. Legacy ``Store.owners/managers/staff``
  M2M membership is intentionally ignored here — the cutover is
  in progress and ``StoreMembership`` is the source of truth.
* KPI cards and quick actions are gated by permission codes. When
  the user lacks the code, the value is ``None`` and the template
  renders a "Locked" state.
* Users with no active membership see the empty-state onboarding
  card instead of the regular dashboard.
"""

from __future__ import annotations

from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render

from apps.permissions.models import Permission, StoreMembership
from apps.permissions.resolver import PermissionResolver
from apps.permissions.services import (
    plan_limit,
    user_has_permission,
    user_roles_in_store,
)
from apps.stores.models import Store


# ---------------------------------------------------------------------------
# Public view
# ---------------------------------------------------------------------------
@login_required
def dashboard_home(request):
    """
    Dashboard home.

    Context keys:

    * ``user``                — the request user
    * ``is_superuser``        — True for Django superusers
    * ``user_stores``         — stores the user can see (active memberships
                                for regular users; all stores for superusers)
    * ``current_store``       — the active store (or ``None``)
    * ``user_has_no_store``   — True when ``user_stores`` is empty
    * ``kpis``                — permission-gated KPI dict
    * ``top_role`` / ``role_names`` — the user's roles in ``current_store``
    * ``plan``                — the active ``SubscriptionPlan`` (or None)
    * ``plan_features``       — feature codes on the active plan
    * ``perm_count``          — number of effective permission codes
    * ``max_users``           — plan seat cap, or None
    """
    user = request.user
    is_superuser = user.is_superuser

    user_stores = _user_stores(user, is_superuser)
    current_store = _resolve_current_store(request, user_stores)

    context: dict[str, Any] = {
        "user": user,
        "is_superuser": is_superuser,
        "user_stores": user_stores,
        "current_store": current_store,
        "user_has_no_store": not user_stores.exists(),
    }

    if current_store is not None:
        context.update(_build_rbac_context(user, current_store, is_superuser))

    return render(request, "dashboard/index.html", context)


@login_required
def switch_store(request, store_id):
    """
    Switch the active store for the current session.

    Authorization:

    * Superusers may switch to any non-deleted store.
    * Regular users must have an **active** ``StoreMembership`` for the
      target store. Legacy M2M membership is intentionally not honored
      here; the cutover plan (§14 of the RBAC plan) keeps the M2M
      in place for read paths but the dashboard enforces the new model.
    """
    user = request.user
    store = Store.objects.filter(id=store_id, is_deleted=False).first()
    if store is None:
        messages.error(request, "Store not found.")
        return redirect("dashboard:home")

    if not user.is_superuser:
        is_member = StoreMembership.objects.filter(
            user=user, store=store, is_active=True,
        ).exists()
        if not is_member:
            messages.error(
                request,
                "You don't have access to this store.",
            )
            return redirect("dashboard:home")

    request.session["current_store_id"] = str(store_id)
    messages.success(request, f"Switched to store: {store.name}")
    return redirect("dashboard:home")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _user_stores(user, is_superuser: bool):
    """Stores the user can see, ordered by name."""
    qs = Store.objects.filter(is_deleted=False)
    if is_superuser:
        return qs.order_by("name")
    member_store_ids = StoreMembership.objects.filter(
        user=user, is_active=True,
    ).values_list("store_id", flat=True)
    return qs.filter(id__in=list(member_store_ids)).order_by("name")


def _resolve_current_store(request, user_stores):
    """
    Honor the session's ``current_store_id`` if it points to a store the
    user can see. Otherwise fall back to the first available store.
    """
    store_id = request.session.get("current_store_id")
    if store_id:
        store = user_stores.filter(id=store_id).first()
        if store is not None:
            return store
    return user_stores.first() if user_stores.exists() else None


def _build_rbac_context(user, store, is_superuser: bool) -> dict[str, Any]:
    """Build the per-store RBAC + KPI context block."""
    roles = user_roles_in_store(user, store)
    top_role = roles[0] if roles else None
    role_names = ", ".join(r.name for r in roles[:3])

    perm_count = (
        Permission.objects.count()
        if is_superuser
        else len(PermissionResolver().grants(user, store))
    )

    kpis = {
        "revenue": _safe_revenue(user, store, is_superuser),
        "orders_count": _safe_count(user, store, "orders.view", is_superuser),
        "customers_count": _safe_count(
            user, store, "customers.view", is_superuser,
        ),
        "low_stock_count": _safe_low_stock(user, store, is_superuser),
    }

    plan = None
    plan_features: list[str] = []
    sub = getattr(store, "subscription", None)
    if sub is not None and sub.is_active():
        plan = sub.plan
        plan_features = list(
            sub.plan.features.values_list("code", flat=True),
        )

    return {
        "top_role": top_role,
        "role_names": role_names,
        "perm_count": perm_count,
        "kpis": kpis,
        "plan": plan,
        "plan_features": plan_features,
        "max_users": plan_limit(store, "max_users") if plan else None,
    }


# ---- KPI helpers ---------------------------------------------------------
# Each helper returns ``None`` when the user lacks the relevant permission
# (or the supporting model is unavailable in this build). Superusers always
# get a real value because the resolver bypasses their check.

def _can_view(user, store, code: str, is_superuser: bool) -> bool:
    if is_superuser:
        return True
    return user_has_permission(user, store, code)


def _safe_revenue(user, store, is_superuser):
    if not _can_view(user, store, "orders.view", is_superuser):
        return None
    try:
        from apps.orders.models import Order
    except Exception:
        return None
    agg = Order.objects.filter(store=store).aggregate(total=Sum("total"))
    return agg["total"] or 0


def _safe_count(user, store, code: str, is_superuser):
    if not _can_view(user, store, code, is_superuser):
        return None
    # Map the permission code to a model. If the app's models.py isn't
    # installed yet, return None so the template renders a locked state.
    model_map = {
        "orders.view": ("orders", "Order"),
        "customers.view": ("customers", "Customer"),
        "products.view": ("products", "Product"),
    }
    app_label, model_name = model_map[code]
    try:
        from django.apps import apps
        model = apps.get_model(app_label, model_name)
    except LookupError:
        return None
    qs = model.objects.all()
    if hasattr(model, "store") and store is not None:
        qs = qs.filter(store=store)
    return qs.count()


def _safe_low_stock(user, store, is_superuser):
    """
    Return the number of low-stock products for the store.

    The product schema isn't fully built yet (apps/products only has
    urls.py), so this helper degrades gracefully:
      * If ``apps.products.models.Product`` is unavailable → ``None``.
      * If the schema lacks a stock field at all → ``None``.
      * If there's no ``store`` FK on the product model → count globally.
    """
    if not _can_view(user, store, "inventory.view", is_superuser):
        return None
    try:
        from django.apps import apps
        Product = apps.get_model("products", "Product")
    except LookupError:
        return None

    field_names = {f.name for f in Product._meta.get_fields()}
    stock_field = next(
        (name for name in ("stock", "inventory", "stock_quantity") if name in field_names),
        None,
    )
    if stock_field is None:
        return None

    qs = Product.objects.all()
    if "store" in field_names and store is not None:
        qs = qs.filter(store=store)

    threshold = 5
    if "reorder_level" in field_names:
        # Pull the comparison values in Python to avoid dialect-specific F().
        items = list(qs.values(stock_field, "reorder_level"))
        return sum(
            1
            for row in items
            if (row[stock_field] or 0) <= (row["reorder_level"] or threshold)
        )

    return qs.filter(**{f"{stock_field}__lte": threshold}).count()
