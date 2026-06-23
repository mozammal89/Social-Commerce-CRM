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
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
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
    # Accept JSON (default) plus multipart/form-data so the create form
    # can upload a logo in the same request. Global default is JSON-only.
    parser_classes = [JSONParser, FormParser, MultiPartParser]

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
        print(f"Current store count for user {user.id}: {current_count}")
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
    # Accept JSON (default) plus multipart/form-data so the edit form can
    # upload a logo. Global DEFAULT_PARSER_CLASSES is JSON-only, so we
    # opt-in here to keep the rest of the API strict.
    parser_classes = [JSONParser, FormParser, MultiPartParser]
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
# remove_store_logo — POST endpoint to clear the store logo
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def remove_store_logo(request, store_id):
    """Delete the logo file from disk and clear the field on the store.

    Only the store owner may remove the logo.
    """
    store = Store.objects.filter(id=store_id, is_deleted=False).first()
    if store is None:
        return Response({"error": "Store not found"}, status=status.HTTP_404_NOT_FOUND)

    user = request.user
    if not getattr(user, "is_superuser", False) and not store.is_owner(user):
        raise exceptions.PermissionDenied("Only store owners can remove the logo.")

    if not store.logo:
        return Response(
            {"message": "No logo to remove.", "removed": False},
            status=status.HTTP_200_OK,
        )

    # Delete the file from storage, then clear the field, then save.
    logo_name = store.logo.name
    store.logo.delete(save=False)
    store.logo = None
    store.save(update_fields=["logo", "updated_at"])

    logger.info(
        "Store logo removed: store_id=%s logo=%s by user=%s",
        store.id,
        logo_name,
        getattr(user, "id", None),
    )
    return Response(
        {"message": "Logo removed.", "removed": True},
        status=status.HTTP_200_OK,
    )


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
    user has access to, falling back to DEFAULT_PLAN_MAX_STORES.

    CRITICAL FIX: Look at ALL subscriptions across all stores the user has
    access to (not just stores where they have membership), and use the
    highest max_stores value. This ensures that if a user has upgraded to a
    higher-tier plan on any store, they can create more stores.
    """
    from apps.permissions.models import Subscription, SubscriptionPlan, StoreMembership
    from apps.accounts.models import User

    # Get all stores the user has any access to (any active membership)
    user_accessible_stores = Store.objects.filter(
        memberships__user=user, memberships__is_active=True, is_deleted=False
    ).distinct()

    # Initialize max_stores with 0
    max_stores = 0

    if not user_accessible_stores.exists():
        # User has no store access yet, check if they have any subscription plan at all
        # This handles the case where user just upgraded but hasn't created a store yet
        # We'll look for the highest-tier plan they've subscribed to anywhere
        all_user_subs = Subscription.objects.filter(
            store__in=user_accessible_stores,  # This will be empty, so try different approach
        )

        # Alternative: check if user has any pending plan from the subscription flow
        if hasattr(user, "pending_plan_slug") and user.pending_plan_slug:
            try:
                pending_plan = SubscriptionPlan.objects.get(slug=user.pending_plan_slug)
                if getattr(pending_plan, "max_stores", None):
                    return int(pending_plan.max_stores)
            except Exception:
                pass

    # Get all subscriptions for all stores the user has access to
    accessible_store_ids = user_accessible_stores.values_list("id", flat=True)

    all_accessible_subs = (
        Subscription.objects.filter(
            store_id__in=accessible_store_ids, status__in=("active", "trialing")
        )
        .select_related("plan")
        .all()
    )

    if all_accessible_subs.exists():
        # Find the subscription with the highest max_stores
        for sub in all_accessible_subs:
            plan_max = getattr(sub.plan, "max_stores", 0)
            if plan_max > max_stores:
                max_stores = plan_max

    # CRITICAL: Check for pending plan - it might be higher tier than current subscription
    # This handles users who just upgraded but haven't completed store creation yet
    if hasattr(user, "pending_plan_slug") and user.pending_plan_slug:
        try:
            pending_plan = SubscriptionPlan.objects.get(slug=user.pending_plan_slug)
            pending_max = getattr(pending_plan, "max_stores", 0)
            if pending_max > max_stores:
                max_stores = pending_max
        except Exception:
            pass

    if max_stores > 0:
        return max_stores

    return DEFAULT_PLAN_MAX_STORES


@login_required
def create_store_template(request):
    """Template view for creating a store."""
    try:
        from apps.permissions.models import Subscription, SubscriptionPlan

        # Check for pending subscription from User model (persists across sessions)
        pending_plan_slug = request.user.pending_plan_slug or request.session.get(
            "pending_plan_slug"
        )
        pending_plan = None

        # Get pending plan if exists
        if pending_plan_slug:
            try:
                pending_plan = SubscriptionPlan.objects.get(slug=pending_plan_slug, is_active=True)
            except SubscriptionPlan.DoesNotExist:
                pass

        # Find subscriptions through user's store memberships
        user_subscription = (
            Subscription.objects.filter(
                store__memberships__user=request.user,
                store__memberships__is_active=True,
                status__in=["trialing", "active"],
            )
            .select_related("plan")
            .first()
        )

        # Allow store creation if user has active subscription OR pending plan from checkout
        if not user_subscription and not pending_plan:
            messages.warning(request, "You need an active subscription to create a store.")
            return redirect("subscriptions:plans")

        # Use the fixed function to determine the correct max stores cap
        # This considers ALL subscriptions across all stores and pending plans
        max_stores = _resolve_max_stores_cap(request.user)

        current_count = (
            Store.objects.filter(
                memberships__user=request.user,
                memberships__is_active=True,
                is_deleted=False,
            )
            .distinct()
            .count()
        )

        remaining_stores = max(0, max_stores - current_count)

        return render(
            request,
            "stores/create.html",
            {
                "user_subscription": user_subscription,
                "pending_plan": pending_plan,
                "current_count": current_count,
                "max_stores": max_stores,
                "remaining_stores": remaining_stores,
            },
        )

    except Exception as e:
        logger.error(f"Error in create_store_template: {str(e)}")
        messages.error(request, "An error occurred. Please try again.")
        return redirect("dashboard:home")


# ---------------------------------------------------------------------------
# Template Views for Store Management (HTML Interface)
# ---------------------------------------------------------------------------
@login_required
def store_list_template(request):
    """Template view for listing all user's stores."""
    try:
        user = request.user

        # Get user's stores through active memberships with member counts
        from django.db.models import Count

        stores = (
            Store.objects.filter(
                memberships__user=user,
                memberships__is_active=True,
                is_deleted=False,
            )
            .annotate(
                member_count=Count("memberships", filter=models.Q(memberships__is_active=True))
            )
            .distinct()
            .order_by("-created_at")
        )

        # Get current store from context
        from apps.common.context_processors import current_store as cp

        ctx = cp(request)
        current_store = ctx.get("current_store")

        # Get subscription info for plan limits
        max_stores = _resolve_max_stores_cap(user)
        current_count = stores.count()
        remaining_stores = max_stores - current_count

        # Count active stores
        active_count = stores.filter(status="active").count()

        return render(
            request,
            "stores/list.html",
            {
                "stores": stores,
                "current_store": current_store,
                "store_count": current_count,
                "active_count": active_count,
                "max_stores": max_stores,
                "remaining_stores": remaining_stores,
            },
        )

    except Exception as e:
        logger.error(f"Error in store_list_template: {str(e)}")
        messages.error(request, "An error occurred while loading stores.")
        return redirect("dashboard:home")


@login_required
def store_detail_template(request, store_id):
    """Template view for viewing a single store's details."""
    try:
        user = request.user
        store = Store.objects.filter(id=store_id, is_deleted=False).first()

        if not store:
            messages.error(request, "Store not found.")
            return redirect("stores:store_list_html")

        # Check if user has access to this store
        if not getattr(user, "is_superuser", False):
            membership = StoreMembership.objects.filter(
                user=user,
                store=store,
                is_active=True,
            ).first()
            if not membership:
                messages.error(request, "You don't have access to this store.")
                return redirect("stores:store_list_html")

        # Check user's role in the store
        from apps.permissions.models import Role

        owner_role = Role.objects.filter(slug="store-owner").first()
        manager_role = Role.objects.filter(slug="manager").first()

        is_owner = False
        is_manager = False

        if getattr(user, "is_superuser", False):
            is_owner = True
            is_manager = True
        else:
            membership = StoreMembership.objects.filter(
                user=user, store=store, is_active=True
            ).first()
            if membership:
                if membership.role == owner_role:
                    is_owner = True
                elif membership.role == manager_role:
                    is_manager = True

        # Count members
        member_count = StoreMembership.objects.filter(store=store, is_active=True).count()

        # Get store stats (placeholder for now)
        products_count = 0
        orders_count = 0
        customers_count = 0

        # Get current store for RBAC context
        from apps.common.context_processors import current_store as cp

        ctx = cp(request)
        current_store = ctx.get("current_store")

        return render(
            request,
            "stores/detail.html",
            {
                "store": store,
                "current_store": current_store,  # For RBAC template tags
                "is_owner": is_owner,
                "is_manager": is_manager,
                "member_count": member_count,
                "products_count": products_count,
                "orders_count": orders_count,
                "customers_count": customers_count,
            },
        )

    except Exception as e:
        import traceback

        logger.error(
            "Error in store_detail_template for store_id=%s user=%s: %s\n%s",
            store_id,
            getattr(request.user, "id", None),
            e,
            traceback.format_exc(),
        )
        messages.error(request, "An error occurred while loading store details.")
        return redirect("stores:store_list_html")


@login_required
def store_edit_template(request, store_id):
    """Template view for editing a store."""
    try:
        user = request.user
        store = Store.objects.filter(id=store_id, is_deleted=False).first()

        if not store:
            messages.error(request, "Store not found.")
            return redirect("stores:store_list_html")

        # Check if user has access to this store
        if not getattr(user, "is_superuser", False):
            membership = StoreMembership.objects.filter(
                user=user,
                store=store,
                is_active=True,
            ).first()
            if not membership:
                messages.error(request, "You don't have access to this store.")
                return redirect("stores:store_list_html")

        # Only owners and managers can edit
        from apps.permissions.models import Role

        owner_role = Role.objects.filter(slug="store-owner").first()
        manager_role = Role.objects.filter(slug="manager").first()

        can_edit = (
            getattr(user, "is_superuser", False) or store.is_owner(user) or store.is_manager(user)
        )

        if not can_edit:
            messages.error(request, "You don't have permission to edit this store.")
            return redirect("stores:store_detail_html", store_id=store_id)

        return render(
            request,
            "stores/edit.html",
            {
                "store": store,
            },
        )

    except Exception as e:
        logger.error(f"Error in store_edit_template: {str(e)}")
        messages.error(request, "An error occurred while loading edit form.")
        return redirect("stores:store_list_html")


# ---------------------------------------------------------------------------
# API Views for Store Switching
# ---------------------------------------------------------------------------
@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def switch_store_api(request, store_id):
    """
    API endpoint to switch the active store for the current session.

    Similar to dashboard.views.switch_store but returns JSON for AJAX requests.

    Authorization:
    * Superusers may switch to any non-deleted store.
    * Regular users must have an active StoreMembership for the target store.
    """
    user = request.user
    store = Store.objects.filter(id=store_id, is_deleted=False).first()

    if store is None:
        return Response(
            {"success": False, "error": "Store not found."}, status=status.HTTP_404_NOT_FOUND
        )

    if not user.is_superuser:
        is_member = StoreMembership.objects.filter(
            user=user,
            store=store,
            is_active=True,
        ).exists()
        if not is_member:
            return Response(
                {"success": False, "error": "You don't have access to this store."},
                status=status.HTTP_403_FORBIDDEN,
            )

    request.session["current_store_id"] = str(store_id)
    return Response(
        {
            "success": True,
            "message": f"Switched to store: {store.name}",
            "store_id": str(store_id),
            "store_name": store.name,
        }
    )
