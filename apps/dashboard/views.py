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

import re

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme


# Sentinel for KPI cards whose supporting model hasn't been implemented
# yet (e.g. ``apps.orders.models.Order`` is missing because that app only
# ships urls.py). The template renders a "Coming soon" state for these,
# instead of the misleading "Locked, require orders.view" message.
KPI_UNAVAILABLE = "unavailable"

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
    Dashboard home with intelligent onboarding flow.

    Context keys:

    * ``user``                — the request user
    * ``is_superuser``        — True for Django superusers
    * ``user_stores``         — stores the user can see (active memberships
                                for regular users; all stores for superusers)
    * ``current_store``       — the active store (or ``None``)
    * ``user_has_no_store``   — True when ``user_stores`` is empty
    * ``user_subscription``   — user's active subscription (or None)
    * ``needs_subscription``  — True if user needs to choose a plan
    * ``has_pending_subscription`` — True if user subscribed but hasn't created store yet
    * ``kpis``                — permission-gated KPI dict
    * ``top_role`` / ``role_names`` — the user's roles in ``current_store``
    * ``plan``                — the active ``SubscriptionPlan`` (or None)
    * ``plan_features``       — feature codes on the active plan
    * ``perm_count``          — number of effective permission codes
    * ``max_users``           — plan seat cap, or None
    * ``show_welcome``        — True if welcome banner should be shown
    """
    user = request.user
    is_superuser = user.is_superuser

    # Check user's subscription status.
    #
    # Order of truth (most authoritative first):
    #   1. Real Subscription row attached to a store the user is a member of.
    #   2. user.pending_plan_slug (a one-shot signup marker, only valid
    #      BEFORE the store is created).
    #   3. None of the above → user needs to pick a plan.
    #
    # `pending_plan_slug` is intentionally NOT used as a primary signal
    # after the user has a real subscription. Otherwise upgrading in
    # place leaves the dashboard thinking the user is in a "pending"
    # onboarding flow.
    user_subscription = None
    needs_subscription = False
    has_pending_subscription = False

    try:
        # Look up the user's active subscription through the tenant-aware
        # resolver. ``store__memberships__user=user`` alone misses
        # tenant-attached rows whose ``store`` FK was cleared by
        # ``promote_subscription_to_tenant`` — that left the dashboard
        # thinking the user had no subscription and looping them back
        # to /subscriptions/plans/ even when a sub existed.
        from apps.subscriptions.services import resolve_user_subscription

        user_subscription = resolve_user_subscription(user)
    except Exception:
        user_subscription = None

    # Trial-expiry banner context. Computed from ``user_subscription``
    # (the same resolver used by the manage page) so the same row drives
    # both banners — a trialing user sees a consistent countdown on
    # both pages. ``is_trial`` + ``trial_days_remaining`` mirrors the
    # context shape in ``apps.subscriptions.views.manage_subscription``
    # so the dashboard template can render the same banner block.
    is_trial = bool(user_subscription and user_subscription.status == "trialing")
    trial_days_remaining = None
    if is_trial and user_subscription.trial_ends_at:
        _trial_end = user_subscription.trial_ends_at
        from django.utils import timezone as _tz

        if _trial_end > _tz.now():
            trial_days_remaining = (_trial_end - _tz.now()).days

    if user_subscription is None:
        # No real subscription. The signup marker may still be set,
        # meaning the user paid but hasn't created their first store yet.
        if user.pending_plan_slug:
            has_pending_subscription = True
        else:
            needs_subscription = True

    # User has memberships but their subscription is canceled/expired/past_due
    # (Fix #3, refined): instead of bouncing them straight back to the
    # manage page, render the dashboard with a clear "subscription needs
    # attention" banner. The previous hard redirect produced a confusing
    # loop combined with the missing Store Management sidebar entry.
    # Computed before the plans-page redirect so a user who has stores
    # but no live subscription lands on the dashboard with a banner
    # (clear re-subscribe CTA) rather than being punted to the
    # first-time-signup plans page.
    subscription_needs_attention = (
        not is_superuser
        and StoreMembership.objects.filter(
            user=user, is_active=True,
        ).exists()
    )

    # If user truly needs a subscription (never had one) and has no
    # pending signup, redirect to the plans page. Users with stores
    # but no live sub are handled by the banner above instead of this
    # redirect — they should see the dashboard so they can keep using
    # what's already set up while deciding whether to renew.
    if (
        needs_subscription
        and not has_pending_subscription
        and not is_superuser
        and not subscription_needs_attention
    ):
        from django.contrib import messages

        messages.info(request, "Welcome! Choose a subscription plan to get started.")
        return redirect("subscriptions:plans")

    user_stores = _user_stores(user, is_superuser)
    current_store = _resolve_current_store(request, user_stores)

    # Bug 1 (URL bypass on the dashboard itself): enforce
    # ``dashboard.view`` *after* we have resolved a store so the
    # resolver has the right context. Superusers always pass.
    # Regular users with no active membership get the onboarding
    # state, which is allowed even without ``dashboard.view`` so
    # they see a useful page.
    if (
        not is_superuser
        and current_store is not None
        and not user_has_permission(user, current_store, "dashboard.view")
    ):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied

    # Plan-changed banner (Fix #5): if the user just upgraded/downgraded,
    # surface that in the template and clear the session flag.
    plan_changed = request.session.pop("plan_changed_just_now", None)

    context: dict[str, Any] = {
        "user": user,
        "is_superuser": is_superuser,
        "user_stores": user_stores,
        "current_store": current_store,
        "user_has_no_store": not user_stores.exists(),
        "user_subscription": user_subscription,
        "needs_subscription": needs_subscription,
        "has_pending_subscription": has_pending_subscription,
        "show_welcome": True,  # Show welcome banner
        # Boolean flags for template checks
        "has_user_subscription": user_subscription is not None,
        # True when the user has stores but no live subscription — the
        # dashboard renders a banner so they can re-subscribe without
        # being force-redirected to the manage page (which used to
        # produce a confusing loop combined with the missing Store
        # Management sidebar entry).
        "subscription_needs_attention": subscription_needs_attention,
        # Plan-change banner payload (or None)
        "plan_changed": plan_changed,
        # Trial-expiry banner context. ``is_trial`` is True only when
        # the resolved subscription is in ``trialing`` status;
        # ``trial_days_remaining`` is the integer day count used to
        # decide whether to render the banner. Mirrors the context
        # shape from ``manage_subscription`` (apps/subscriptions/views.py)
        # so the same banner template logic works in both places.
        "is_trial": is_trial,
        "trial_days_remaining": trial_days_remaining,
    }

    # If user has pending subscription, get plan details
    if has_pending_subscription and user.pending_plan_slug:
        try:
            from apps.subscriptions.models import SubscriptionPlan
            pending_plan = SubscriptionPlan.objects.get(slug=user.pending_plan_slug)
            context["pending_plan"] = pending_plan
        except SubscriptionPlan.DoesNotExist:
            pass

    if current_store is not None:
        context.update(_build_rbac_context(user, current_store, is_superuser))

    return render(request, "dashboard/index.html", context)


@login_required
def switch_store(request, store_id):
    """
    Switch the active store for the current session.

    After switching, the user is sent back to the page they were on
    via the ``next`` query string (validated to be a same-host URL to
    prevent open-redirect attacks). Falls back to the dashboard home
    if ``next`` is missing or unsafe.

    Authorization:

    * Superusers may switch to any non-deleted store.
    * Regular users must have an **active** ``StoreMembership`` for the
      target store. Legacy M2M membership is intentionally not honored
      here; the cutover plan (§14 of the RBAC plan) keeps the M2M
      in place for read paths but the dashboard enforces the new model.
    """
    fallback = redirect("dashboard:home")
    user = request.user
    store = Store.objects.filter(id=store_id, is_deleted=False).first()
    if store is None:
        messages.error(request, "Store not found.")
        return fallback

    if not user.is_superuser:
        is_member = StoreMembership.objects.filter(
            user=user,
            store=store,
            is_active=True,
        ).exists()
        if not is_member:
            messages.error(
                request,
                "You don't have access to this store.",
            )
            return fallback

    request.session["current_store_id"] = str(store_id)
    messages.success(request, f"Switched to store: {store.name}")

    # Honor ``?next=<url>`` so the user lands back on the page they
    # were viewing. Validate that the URL is safe (same host, no
    # scheme override) to prevent open-redirect attacks.
    next_url = request.GET.get("next", "")
    if next_url and url_has_allowed_host_and_scheme(
        next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return redirect(_swap_store_id_in_path(next_url, str(store_id)))
    return fallback


# Match a UUID-shaped path segment so we can replace the old
# ``<uuid:store_id>`` in a ``next`` URL with the newly-switched-to
# store. The non-greedy ``.*?`` prefix anchors the match to the
# *first* UUID in the path — every store-scoped route in this
# project (e.g. ``/settings/team/<store_id>/``,
# ``/stores/<store_id>/view/``) puts the store UUID before any other
# UUIDs, so deeper ones like ``<membership_id>`` in
# ``/settings/team/<store>/change-role/<member>/`` are left alone.
_UUID_SEGMENT_RE = re.compile(
    r"^(.*?)/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(.*)$"
)


def _swap_store_id_in_path(next_url: str, new_store_id: str) -> str:
    """Replace the first UUID in ``next_url`` with ``new_store_id``.

    Store-scoped URLs all put the store UUID in the path (e.g.
    ``/settings/team/<store_id>/``). When the user switches stores
    while on such a page, the original URL still references the old
    store, so the new session value would be ignored — and
    ``@current_store`` resolves the URL kwarg over the session. By
    substituting the UUID, the user lands on the same view but with
    the new store context.

    URLs that don't contain a UUID (e.g. ``/dashboard/``, ``/``) are
    returned unchanged — those routes are store-agnostic and don't
    need any substitution.
    """
    match = _UUID_SEGMENT_RE.match(next_url)
    if match is None:
        return next_url
    prefix, _old_uuid, rest = match.groups()
    return f"{prefix}/{new_store_id}{rest}"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _user_stores(user, is_superuser: bool):
    """Stores the user can see, ordered by name."""
    qs = Store.objects.filter(is_deleted=False)
    if is_superuser:
        return qs.order_by("name")
    member_store_ids = StoreMembership.objects.filter(
        user=user,
        is_active=True,
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
            user,
            store,
            "customers.view",
            is_superuser,
        ),
        "low_stock_count": _safe_low_stock(user, store, is_superuser),
    }

    plan = None
    plan_features: list[str] = []
    # Resolve the active subscription through the same tenant-aware
    # resolver used elsewhere, instead of just reading the legacy
    # ``store.subscription`` reverse. The legacy reverse is None for
    # subscriptions that have been promoted to a tenant — i.e. exactly
    # the state users reach after their first in-place upgrade — which
    # left the dashboard header blank ("Plan: …") and the seat-cap
    # badge missing even when the user had a perfectly valid active
    # subscription.
    from apps.subscriptions.services import get_active_subscription

    sub = get_active_subscription(store)
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
        return KPI_UNAVAILABLE
    agg = Order.objects.filter(store=store).aggregate(total=Sum("total"))
    return agg["total"] or 0


def _safe_count(user, store, code: str, is_superuser):
    if not _can_view(user, store, code, is_superuser):
        return None
    # Map the permission code to a model. If the app's models.py isn't
    # installed yet, return KPI_UNAVAILABLE so the template renders a
    # "Coming soon" state instead of misleadingly saying "Locked".
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
        return KPI_UNAVAILABLE
    qs = model.objects.all()
    if hasattr(model, "store") and store is not None:
        qs = qs.filter(store=store)
    return qs.count()


def _safe_low_stock(user, store, is_superuser):
    """
    Return the number of low-stock products for the store.

    The product schema isn't fully built yet (apps/products only has
    urls.py), so this helper degrades gracefully:
      * If ``apps.products.models.Product`` is unavailable → ``KPI_UNAVAILABLE``.
      * If the schema lacks a stock field at all → ``KPI_UNAVAILABLE``.
      * If there's no ``store`` FK on the product model → count globally.
    """
    if not _can_view(user, store, "inventory.view", is_superuser):
        return None
    try:
        from django.apps import apps

        Product = apps.get_model("products", "Product")
    except LookupError:
        return KPI_UNAVAILABLE

    field_names = {f.name for f in Product._meta.get_fields()}
    stock_field = next(
        (name for name in ("stock", "inventory", "stock_quantity") if name in field_names),
        None,
    )
    if stock_field is None:
        return KPI_UNAVAILABLE

    qs = Product.objects.all()
    if "store" in field_names and store is not None:
        qs = qs.filter(store=store)

    threshold = 5
    if "reorder_level" in field_names:
        # Pull the comparison values in Python to avoid dialect-specific F().
        items = list(qs.values(stock_field, "reorder_level"))
        return sum(
            1 for row in items if (row[stock_field] or 0) <= (row["reorder_level"] or threshold)
        )

    return qs.filter(**{f"{stock_field}__lte": threshold}).count()
