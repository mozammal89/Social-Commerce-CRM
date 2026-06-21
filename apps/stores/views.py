"""
Views for Store management.

Bug fixes applied (per RBAC audit plan):

* Bug 1: store-scoped views now require an active membership via
  ``@current_store`` (function views) or ``IsStoreMember`` + ``HasPermission``
  (DRF CBVs).
* Bug 2: queryset filters use ``StoreMembership`` (active) instead of
  the legacy ``owners/managers/staff`` M2M.
* Bug 4: ``MyStoresView`` returns stores where the user has any active
  membership (not just owned).
* Bug 8: ``manage_store_staff`` routes through ``add_member`` /
  ``remove_member`` instead of the legacy M2M helpers, which means cache
  invalidation and audit emission fire automatically (Bug 11).
* Bug 9: ``perform_create`` enforces the plan's ``max_stores`` cap.
"""

from __future__ import annotations

import logging

from django.db import models
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from rest_framework import generics, status, permissions, exceptions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.stores.models import Store
from apps.stores.serializers import (
    StoreSerializer,
    StoreCreateSerializer,
    StoreUpdateSerializer,
    StoreStaffSerializer,
)
from apps.accounts.models import User
from apps.permissions.decorators import current_store
from apps.permissions.permissions import IsStoreMember, HasStoreRole
from apps.permissions.services import (
    add_member,
    remove_member,
    assert_within_plan_limit,
)
from apps.permissions.models import Role, StoreMembership


logger = logging.getLogger("apps.stores")


# Map a serializer "role" string to the system role slug and store-owner level.
# (The serializer still accepts "manager"/"staff" as legacy input; we resolve
# to the canonical system role here.)
ROLE_SLUG_FOR_LEGACY = {
    "manager": "manager",
    "staff": "viewer",  # legacy "staff" maps to viewer-role membership
}


# ---------------------------------------------------------------------------
# Bug 9 — fallback when no subscription exists yet
# ---------------------------------------------------------------------------
DEFAULT_PLAN_MAX_STORES = 5  # generous default for tests / new users


# ---------------------------------------------------------------------------
# StoreListView
# ---------------------------------------------------------------------------
class StoreListView(generics.ListCreateAPIView):
    """View for listing and creating stores."""

    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Return stores where the user has an active membership."""
        user = self.request.user
        if getattr(user, "is_superuser", False):
            return Store.objects.filter(is_deleted=False).distinct()
        return Store.objects.filter(
            memberships__user=user,
            memberships__is_active=True,
            is_deleted=False,
        ).distinct()

    def get_serializer_class(self):
        if self.request.method == "POST":
            return StoreCreateSerializer
        return StoreSerializer

    def perform_create(self, serializer):
        """Save store with plan-limit guard (Bug 9)."""
        user = self.request.user
        current_count = (
            Store.objects.filter(
                memberships__user=user,
                memberships__is_active=True,
                is_deleted=False,
            )
            .distinct()
            .count()
        )

        # Determine cap. For new users we may not have a subscription yet,
        # so fall back to a generous default plan cap.
        cap = _resolve_max_stores_cap(user)
        if current_count >= cap:
            from apps.permissions.exceptions import PlanLimitExceeded

            raise PlanLimitExceeded("max_stores", current_count, cap)

        store = serializer.save()
        # Make the creator the store-owner via the legacy M2M for any
        # legacy read paths still relying on it. The proper membership
        # is created by the serializer (which also calls add_owner).
        store.add_owner(user)


# ---------------------------------------------------------------------------
# StoreDetailView
# ---------------------------------------------------------------------------
class StoreDetailView(generics.RetrieveUpdateDestroyAPIView):
    """View for retrieving, updating, and deleting stores."""

    serializer_class = StoreUpdateSerializer
    permission_classes = [
        permissions.IsAuthenticated,
        IsStoreMember,
        HasStoreRole.with_level(Role.LEVEL_MANAGER),
    ]
    lookup_field = "id"

    def get_queryset(self):
        """Return stores accessible via active membership."""
        user = self.request.user
        if getattr(user, "is_superuser", False):
            return Store.objects.filter(is_deleted=False)
        return Store.objects.filter(
            memberships__user=user,
            memberships__is_active=True,
            is_deleted=False,
        ).distinct()

    def get_serializer_class(self):
        if self.request.method == "GET":
            return StoreSerializer
        return StoreUpdateSerializer

    def perform_update(self, serializer):
        """Update store with validation."""
        store = self.get_object()
        user = self.request.user

        if not getattr(user, "is_superuser", False) and not store.is_owner(user):
            raise exceptions.PermissionDenied(
                "Only store owners can update store information.",
            )

        serializer.save()

    def perform_destroy(self, instance):
        """Soft delete store."""
        user = self.request.user

        if not getattr(user, "is_superuser", False) and not instance.is_owner(user):
            raise exceptions.PermissionDenied(
                "Only store owners can delete stores.",
            )

        instance.soft_delete(deleted_by=user)


# ---------------------------------------------------------------------------
# manage_store_staff — routes through add_member/remove_member
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
@current_store
def manage_store_staff(request, store_id=None):
    """View for managing store staff.

    Bug 8: routes through ``add_member``/``remove_member`` so that cache
    invalidation and audit emission fire via the existing signal handlers
    (Bug 11).
    """
    store = request.store
    if store is None:
        return Response(
            {"error": "Store not found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    user = request.user
    if not getattr(user, "is_superuser", False) and not store.is_owner(user):
        raise exceptions.PermissionDenied(
            "Only store owners can manage staff.",
        )

    serializer = StoreStaffSerializer(data=request.data, context={"store": store})
    serializer.is_valid(raise_exception=True)

    user_id = serializer.validated_data["user_id"]
    role_key = serializer.validated_data["role"]

    target_user = User.objects.get(id=user_id)

    role_slug = ROLE_SLUG_FOR_LEGACY.get(role_key, role_key)
    try:
        role = Role.objects.get(slug=role_slug, store=None)
    except Role.DoesNotExist:
        return Response(
            {"error": f"Unknown role '{role_slug}'."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if serializer.validated_data["action"] == "add":
        # max_users enforcement: only count when this is a new membership.
        existing = StoreMembership.objects.filter(
            user=target_user,
            store=store,
            role=role,
        ).first()
        if existing is None or not existing.is_active:
            from apps.subscriptions.services import enforce_plan_limit

            current_seats = StoreMembership.objects.filter(
                store=store,
                is_active=True,
            ).count()
            enforce_plan_limit(store, "max_users", current_seats)
        add_member(target_user, store, role, invited_by=user)
        message = f"User added as {role.name}"
    else:
        remove_member(target_user, store, role)
        message = f"User removed as {role.name}"

    return Response({"message": message}, status=status.HTTP_200_OK)


# ---------------------------------------------------------------------------
# MyStoresView
# ---------------------------------------------------------------------------
class MyStoresView(generics.ListAPIView):
    """View for listing current user's stores.

    Bug 4: returns stores where the user has any active membership,
    not just stores they own.
    """

    serializer_class = StoreSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        if getattr(user, "is_superuser", False):
            return Store.objects.filter(is_deleted=False).distinct()
        return (
            Store.objects.filter(
                memberships__user=user,
                memberships__is_active=True,
                is_deleted=False,
            )
            .distinct()
            .order_by("name")
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _resolve_max_stores_cap(user) -> int:
    """Return the max_stores cap from the highest active subscription the
    user has, falling back to DEFAULT_PLAN_MAX_STORES.
    """
    from apps.permissions.models import Subscription, SubscriptionPlan

    sub = (
        Subscription.objects.filter(
            store__memberships__user=user,
            store__memberships__is_active=True,
            status__in=("active", "trialing"),
        )
        .select_related("plan")
        .order_by("-plan__max_stores")
        .first()
    )
    if sub is not None and getattr(sub.plan, "max_stores", None):
        return int(sub.plan.max_stores)

    # Fallback: pick the public free/trial plan if any.
    free_plan = (
        SubscriptionPlan.objects.filter(is_active=True, is_public=True)
        .order_by("-max_stores")
        .first()
    )
    if free_plan is not None and getattr(free_plan, "max_stores", None):
        return int(free_plan.max_stores)

    return DEFAULT_PLAN_MAX_STORES


@login_required
def create_store_template(request):
    """Template view for creating a store."""
    try:
        from apps.permissions.models import Subscription

        # Check for pending subscription from User model (persists across sessions)
        pending_plan_slug = request.user.pending_plan_slug or request.session.get("pending_plan_slug")

        # Find subscriptions through user's store memberships
        user_subscription = Subscription.objects.filter(
            store__memberships__user=request.user,
            store__memberships__is_active=True,
            status__in=["trialing", "active"]
        ).select_related('plan').first()

        # Allow store creation if user has active subscription OR pending plan from checkout
        if not user_subscription and not pending_plan_slug:
            messages.warning(request, "You need an active subscription to create a store.")
            return redirect("subscriptions:plans")

        # Determine which plan to use for limits
        if pending_plan_slug:
            from apps.permissions.models import SubscriptionPlan
            plan = SubscriptionPlan.objects.get(slug=pending_plan_slug)
            max_stores = plan.max_stores
        else:
            max_stores = user_subscription.plan.max_stores

        current_count = (
            Store.objects.filter(
                memberships__user=request.user,
                memberships__is_active=True,
                is_deleted=False,
            )
            .distinct()
            .count()
        )

        remaining_stores = max_stores - current_count

        return render(
            request,
            "stores/create.html",
            {
                "user_subscription": user_subscription,
                "current_count": current_count,
                "max_stores": max_stores,
                "remaining_stores": remaining_stores,
            },
        )

    except Exception as e:
        logger.error(f"Error in create_store_template: {str(e)}")
        messages.error(request, "An error occurred. Please try again.")
        return redirect("dashboard:home")
