"""
Views for subscription management.
"""

from rest_framework import generics, status, permissions, serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render


def _resolve_current_store_for_user(request, user):
    """Pick the store the user is currently working on.

    Resolution order:
      1. ``request.session['current_store_id']`` if it points to a store
         the user has an active membership for.
      2. The user's first store (by ``joined_at`` on the membership).

    Returns a ``Store`` instance or ``None`` if the user has no stores.
    """
    qs = (
        Store.objects.filter(
            memberships__user=user,
            memberships__is_active=True,
            is_deleted=False,
        )
        .distinct()
        .order_by("memberships__joined_at")
    )

    session_store_id = (
        request.session.get("current_store_id") if hasattr(request, "session") else None
    )
    if session_store_id:
        store = qs.filter(id=session_store_id).first()
        if store is not None:
            return store

    return qs.first()


from django.utils import timezone
from django.db import transaction

from apps.permissions.models import SubscriptionPlan, StoreMembership
from apps.stores.models import Store
from apps.permissions.services import (
    add_member,
    plan_limit,
    user_roles_in_store,
    active_memberships,
)
from apps.permissions.models import Role
from .services import (
    create_trial_subscription,
    create_paid_subscription,
    create_trial_subscription_for_tenant,
    create_paid_subscription_for_tenant,
    cancel_subscription,
    upgrade_subscription,
    downgrade_subscription,
    get_active_subscription,
    check_plan_limits,
    enforce_plan_limit,
    transition_status,
    check_trial_expiry,
)
from .constants import (
    STATUS_ACTIVE,
    STATUS_PAST_DUE,
    STATUS_TRIALING,
    BILLING_MONTHLY,
    BILLING_YEARLY,
)
from .exceptions import (
    SubscriptionAlreadyExistsError,
    PlanLimitExceeded,
    TransitionNotAllowedError,
)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------


class PlanListSerializer(serializers.ModelSerializer):
    """Serializer for listing subscription plans."""

    features = serializers.SerializerMethodField()
    monthly_price = serializers.SerializerMethodField()
    yearly_price = serializers.SerializerMethodField()

    class Meta:
        model = SubscriptionPlan
        fields = [
            "id",
            "name",
            "slug",
            "description",
            "price",
            "currency",
            "billing_period",
            "max_stores",
            "max_users",
            "max_products",
            "max_orders_per_month",
            "max_warehouses",
            "trial_days",
            "features",
            "monthly_price",
            "yearly_price",
        ]

    def get_features(self, obj):
        """Get feature list for the plan."""
        return list(obj.features.values_list("code", flat=True))

    def get_monthly_price(self, obj):
        """Get monthly price equivalent."""
        if obj.billing_period == BILLING_MONTHLY:
            return str(obj.price)
        return str(obj.price / 12)

    def get_yearly_price(self, obj):
        """Get yearly price equivalent."""
        if obj.billing_period == BILLING_YEARLY:
            return str(obj.price)
        return str(obj.price * 12)


class PlanDetailSerializer(PlanListSerializer):
    """Detailed serializer for subscription plans."""

    class Meta(PlanListSerializer.Meta):
        fields = PlanListSerializer.Meta.fields + ["is_active", "is_public", "sort_order"]


class SubscriptionCreateSerializer(serializers.Serializer):
    """Serializer for creating a subscription."""

    plan_slug = serializers.SlugField()
    billing_period = serializers.ChoiceField(
        choices=[BILLING_MONTHLY, BILLING_YEARLY],
        default=BILLING_MONTHLY,
    )
    start_trial = serializers.BooleanField(default=True)
    store_name = serializers.CharField(required=False)


class SubscriptionCancelSerializer(serializers.Serializer):
    """Serializer for canceling a subscription."""

    cancel_at_period_end = serializers.BooleanField(default=True)
    reason = serializers.CharField(required=False, allow_blank=True)


class SubscriptionUpdateSerializer(serializers.Serializer):
    """Serializer for updating subscription plans."""

    new_plan_slug = serializers.SlugField()
    effective_immediately = serializers.BooleanField(default=False)


# ---------------------------------------------------------------------------
# Template Views
# ---------------------------------------------------------------------------


@login_required
def subscription_plans(request):
    """
    Display available subscription plans for the customer to choose from.
    This is the main entry point for customers after signup/login.
    """
    user = request.user

    # Get user's current subscription if exists
    current_subscription = None
    current_store = None

    # Check if user has any store memberships
    memberships = active_memberships(None).filter(user=user)

    if memberships.exists():
        # User already has access to stores
        return redirect("dashboard:home")

    # Separate monthly and yearly plans
    monthly_plans = SubscriptionPlan.objects.filter(
        is_active=True, is_public=True, billing_period="monthly"
    ).order_by("sort_order", "price")

    yearly_plans = SubscriptionPlan.objects.filter(
        is_active=True, is_public=True, billing_period="yearly"
    ).order_by("sort_order", "price")

    context = {
        "user": user,
        "monthly_plans": monthly_plans,
        "yearly_plans": yearly_plans,
        "current_subscription": current_subscription,
        "current_store": current_store,
        "billing_periods": {
            "monthly": BILLING_MONTHLY,
            "yearly": BILLING_YEARLY,
        },
    }

    return render(request, "subscriptions/plans.html", context)


@login_required
def subscription_checkout(request, plan_slug):
    """
    Handle subscription checkout process.
    Records the plan choice and redirects to store setup.
    """
    user = request.user

    try:
        plan = SubscriptionPlan.objects.get(slug=plan_slug, is_active=True)
    except SubscriptionPlan.DoesNotExist:
        return redirect("subscriptions:plans")

    # Check if user already has subscription (through store membership)
    if active_memberships(None).filter(user=user).exists():
        return redirect("dashboard:home")

    # Handle POST - Record plan choice and redirect to store setup
    if request.method == "POST":
        from django.utils import timezone

        start_trial = request.POST.get("start_trial", "true").lower() == "true"

        # Store pending subscription in User model (persists across sessions)
        user.pending_plan_slug = plan.slug
        user.pending_trial_start = start_trial
        user.pending_subscription_date = timezone.now()
        user.save(
            update_fields=["pending_plan_slug", "pending_trial_start", "pending_subscription_date"]
        )

        # Also store in session for immediate use
        request.session["pending_plan_slug"] = plan.slug
        request.session["pending_plan_name"] = plan.name
        request.session["pending_trial"] = start_trial
        request.session["subscription_plan"] = plan.name
        request.session["trial_days"] = plan.trial_days if start_trial else 0

        # Redirect to welcome page where user will create their store
        return redirect("subscriptions:welcome")

    # Handle GET - Display checkout page
    billing_period = request.GET.get("billing", BILLING_MONTHLY)
    start_trial = request.GET.get("trial", "true").lower() == "true"

    context = {
        "user": user,
        "plan": plan,
        "billing_period": billing_period,
        "start_trial": start_trial,
        "total_amount": plan.price
        if billing_period == plan.billing_period
        else (plan.price * 12 if plan.billing_period == BILLING_MONTHLY else plan.price / 12),
    }

    return render(request, "subscriptions/checkout.html", context)


@login_required
def subscription_success(request):
    """
    Display success page after successful subscription.
    """
    return render(request, "subscriptions/success.html")


@login_required
def subscription_welcome(request):
    """
    Welcome page after successful subscription.
    Guides users to set up their store.
    """
    user = request.user
    subscription_plan = request.session.get("subscription_plan", "")
    trial_days = request.session.get("trial_days", 0)
    pending_plan = None

    # Check for pending subscription in User model (persists across sessions)
    if user.pending_plan_slug:
        try:
            from apps.permissions.models import SubscriptionPlan

            pending_plan = SubscriptionPlan.objects.get(slug=user.pending_plan_slug)
            # If not in session, use from User model
            if not subscription_plan:
                subscription_plan = pending_plan.name
            if not trial_days and user.pending_trial_start:
                trial_days = pending_plan.trial_days
        except SubscriptionPlan.DoesNotExist:
            pass

    # Check if user has stores
    has_stores = Store.objects.filter(
        memberships__user=user, memberships__is_active=True, is_deleted=False
    ).exists()

    context = {
        "subscription_plan": subscription_plan,
        "trial_days": trial_days,
        "has_stores": has_stores,
        "pending_plan": pending_plan,
    }

    # Clear session data (but keep User model data for persistence)
    request.session.pop("subscription_plan", None)
    request.session.pop("trial_days", None)

    return render(request, "subscriptions/welcome.html", context)


@login_required
def manage_subscription(request):
    """
    Allow customers to manage their subscription.
    Updated for tenant-based architecture.
    """
    user = request.user

    # Get user's tenant subscription (new architecture)
    from apps.accounts.models import Tenant

    subscription = None
    try:
        tenant = Tenant.objects.filter(owner=user).first()
        if tenant and hasattr(tenant, "subscription") and tenant.subscription:
            subscription = tenant.subscription
    except Exception:
        pass

    # Fallback to store-based subscription (migration period)
    if not subscription:
        memberships = active_memberships(None).filter(user=user)
        if memberships.exists():
            # Resolve the store the user is currently viewing (session > first).
            store = _resolve_current_store_for_user(request, user)
            if store:
                subscription = get_active_subscription(store)

    if not subscription:
        return redirect("subscriptions:plans")

    # Get a store for limit checking (any store under tenant or current store)
    store_for_limits = None
    if subscription.tenant:
        store_for_limits = subscription.tenant.stores.first()
    else:
        memberships = active_memberships(None).filter(user=user)
        if memberships.exists():
            store_for_limits = _resolve_current_store_for_user(request, user)

    if not store_for_limits:
        return redirect("subscriptions:plans")

    # Check plan limits
    limits_info = check_plan_limits(store_for_limits)

    # Get available upgrade/downgrade plans
    current_plan = subscription.plan
    available_plans = (
        SubscriptionPlan.objects.filter(is_active=True, is_public=True)
        .exclude(id=current_plan.id)
        .order_by("price")
    )

    upgrade_plans = [p for p in available_plans if p.price > current_plan.price]
    downgrade_plans = [p for p in available_plans if p.price < current_plan.price]

    # Get subscription events
    events = subscription.events.order_by("-occurred_at")[:10]

    context = {
        "user": user,
        "subscription": subscription,
        "plan": current_plan,
        "limits_info": limits_info,
        "upgrade_plans": upgrade_plans,
        "downgrade_plans": downgrade_plans,
        "events": events,
        "can_cancel": subscription.status in [STATUS_ACTIVE, STATUS_TRIALING],
        "can_upgrade": subscription.status == STATUS_ACTIVE,
        "is_trial": subscription.status == STATUS_TRIALING,
        "trial_days_remaining": None,
    }

    if subscription.trial_ends_at:
        trial_end = subscription.trial_ends_at
        if trial_end > timezone.now():
            days_remaining = (trial_end - timezone.now()).days
            context["trial_days_remaining"] = days_remaining

    return render(request, "subscriptions/manage.html", context)


# ---------------------------------------------------------------------------
# API Views
# ---------------------------------------------------------------------------


class PlanListView(generics.ListAPIView):
    """API view to list all available subscription plans."""

    serializer_class = PlanListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SubscriptionPlan.objects.filter(is_active=True, is_public=True).order_by(
            "sort_order", "price"
        )


class PlanDetailView(generics.RetrieveAPIView):
    """API view to get details of a specific plan."""

    serializer_class = PlanDetailSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "slug"

    def get_queryset(self):
        return SubscriptionPlan.objects.filter(is_active=True, is_public=True)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def create_subscription(request):
    """
    Create a new subscription for the authenticated user.

    This handles both trial and paid subscription creation.
    """
    serializer = SubscriptionCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user = request.user

    # Check if user already has subscription
    if active_memberships(None).filter(user=user).exists():
        return Response(
            {"error": "You already have an active subscription"}, status=status.HTTP_400_BAD_REQUEST
        )

    try:
        plan = SubscriptionPlan.objects.get(
            slug=serializer.validated_data["plan_slug"], is_active=True
        )
    except SubscriptionPlan.DoesNotExist:
        return Response({"error": "Plan not found"}, status=status.HTTP_404_NOT_FOUND)

    try:
        with transaction.atomic():
            # Create tenant first (new tenant-based architecture)
            from apps.accounts.models import Tenant

            tenant_slug = f"{user.email.split('@')[0]}-workspace"
            tenant, created = Tenant.objects.get_or_create(
                slug=tenant_slug,
                defaults={
                    "name": f"{user.get_full_name()}'s Workspace",
                    "owner": user,
                    "is_active": True,
                },
            )

            # Create subscription linked to tenant
            if serializer.validated_data["start_trial"]:
                subscription = create_trial_subscription_for_tenant(
                    tenant, plan, actor=user, trial_days=plan.trial_days
                )
            else:
                # For paid subscriptions, you would integrate with payment gateway here
                # For now, we'll create it as active
                subscription = create_paid_subscription_for_tenant(tenant, plan, actor=user)

            # Create store linked to tenant
            store_name = serializer.validated_data.get(
                "store_name", f"{user.get_full_name()}'s Store"
            )
            store = Store.objects.create(name=store_name, tenant=tenant)

            # Make the user the store owner
            owner_role = Role.objects.get(slug="store-owner", store=None)
            add_member(user, store, owner_role)

            return Response(
                {
                    "message": "Subscription created successfully",
                    "subscription_id": str(subscription.id),
                    "store_id": str(store.id),
                    "status": subscription.status,
                    "plan": plan.name,
                    "trial_ends_at": subscription.trial_ends_at.isoformat()
                    if subscription.trial_ends_at
                    else None,
                },
                status=status.HTTP_201_CREATED,
            )

    except SubscriptionAlreadyExistsError:
        return Response(
            {"error": "Store already has an active subscription"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def cancel_subscription_view(request):
    """
    Cancel the current user's subscription.
    """
    serializer = SubscriptionCancelSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user = request.user

    # Get user's tenant subscription (new architecture)
    from apps.accounts.models import Tenant

    subscription = None
    try:
        tenant = Tenant.objects.filter(owner=user).first()
        if tenant and hasattr(tenant, "subscription") and tenant.subscription:
            subscription = tenant.subscription
    except Exception:
        pass

    # Fallback to store-based subscription (migration period)
    if not subscription:
        memberships = active_memberships(None).filter(user=user)
        if memberships.exists():
            store = _resolve_current_store_for_user(request, user)
            if store:
                subscription = get_active_subscription(store)

    if not subscription:
        return Response({"error": "No active subscription found"}, status=status.HTTP_404_NOT_FOUND)

    try:
        with transaction.atomic():
            cancel_subscription(
                subscription,
                cancel_at_period_end=serializer.validated_data["cancel_at_period_end"],
                actor=user,
                reason=serializer.validated_data.get("reason"),
            )

            return Response(
                {
                    "message": "Subscription cancelled successfully",
                    "status": subscription.status,
                    "ends_at": subscription.ends_at.isoformat() if subscription.ends_at else None,
                }
            )

    except TransitionNotAllowedError as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def update_subscription_plan(request):
    """
    Upgrade or downgrade subscription plan.
    Updated for tenant-based architecture.
    """
    serializer = SubscriptionUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user = request.user

    # Get user's tenant subscription (new architecture)
    from apps.accounts.models import Tenant

    subscription = None
    try:
        tenant = Tenant.objects.filter(owner=user).first()
        if tenant and hasattr(tenant, "subscription") and tenant.subscription:
            subscription = tenant.subscription
    except Exception:
        pass

    # Fallback to store-based subscription (migration period)
    if not subscription:
        memberships = active_memberships(None).filter(user=user)
        if memberships.exists():
            store = _resolve_current_store_for_user(request, user)
            if store:
                subscription = get_active_subscription(store)

    if not subscription:
        return Response({"error": "No active subscription found"}, status=status.HTTP_404_NOT_FOUND)

    try:
        new_plan = SubscriptionPlan.objects.get(
            slug=serializer.validated_data["new_plan_slug"], is_active=True
        )
    except SubscriptionPlan.DoesNotExist:
        return Response({"error": "Plan not found"}, status=status.HTTP_404_NOT_FOUND)

    try:
        with transaction.atomic():
            if new_plan.price > subscription.plan.price:
                # Upgrade
                subscription = upgrade_subscription(subscription, new_plan, actor=user)
                action = "upgraded"
            elif new_plan.price < subscription.plan.price:
                # Downgrade
                effective_immediately = serializer.validated_data["effective_immediately"]
                subscription = downgrade_subscription(
                    subscription,
                    new_plan,
                    actor=user,
                    effective_at_period_end=not effective_immediately,
                )
                action = "downgraded"
            else:
                return Response(
                    {"error": "Cannot switch to same price plan"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Mark the session so the dashboard renders a "plan changed"
            # success banner on the user's next request. Cleared on read.
            request.session["plan_changed_just_now"] = {
                "action": action,
                "plan_name": new_plan.name,
                "plan_slug": new_plan.slug,
                "effective_immediately": (
                    action == "upgraded"
                    or serializer.validated_data.get("effective_immediately", False)
                ),
            }

            return Response(
                {
                    "message": f"Subscription {action} successfully",
                    "plan": new_plan.name,
                    "status": subscription.status,
                }
            )

    except Exception as e:
        return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def get_current_subscription(request):
    """
    Get the current user's subscription details.
    """
    user = request.user

    memberships = active_memberships(None).filter(user=user)

    if not memberships.exists():
        return Response({"error": "No subscription found"}, status=status.HTTP_404_NOT_FOUND)

    store = _resolve_current_store_for_user(request, user)
    if store is None:
        return Response({"error": "No active subscription found"}, status=status.HTTP_404_NOT_FOUND)
    subscription = get_active_subscription(store)

    if not subscription:
        return Response({"error": "No active subscription found"}, status=status.HTTP_404_NOT_FOUND)

    # Get plan limits info
    limits_info = check_plan_limits(store)

    return Response(
        {
            "subscription": {
                "id": str(subscription.id),
                "status": subscription.status,
                "is_active": subscription.is_active(),
                "plan": {
                    "id": str(subscription.plan.id),
                    "name": subscription.plan.name,
                    "slug": subscription.plan.slug,
                    "price": str(subscription.plan.price),
                    "currency": subscription.plan.currency,
                },
                "trial_ends_at": subscription.trial_ends_at.isoformat()
                if subscription.trial_ends_at
                else None,
                "current_period_end": subscription.current_period_end.isoformat()
                if subscription.current_period_end
                else None,
                "starts_at": subscription.starts_at.isoformat() if subscription.starts_at else None,
                "ends_at": subscription.ends_at.isoformat() if subscription.ends_at else None,
            },
            "limits": limits_info,
        }
    )


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def check_subscription_limits(request):
    """
    Check current subscription limits and usage.
    """
    user = request.user

    memberships = active_memberships(None).filter(user=user)

    if not memberships.exists():
        return Response({"error": "No subscription found"}, status=status.HTTP_404_NOT_FOUND)

    store = _resolve_current_store_for_user(request, user)
    if store is None:
        return Response({"error": "No subscription found"}, status=status.HTTP_404_NOT_FOUND)
    limits_info = check_plan_limits(store)

    return Response(limits_info)
