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
    reactivate_subscription,
    upgrade_subscription,
    downgrade_subscription,
    change_plan,
    get_active_subscription,
    check_plan_limits,
    enforce_plan_limit,
    transition_status,
    check_trial_expiry,
    promote_subscription_to_tenant,
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

    ``?upgrade=1`` query parameter bypasses the "you already have a
    subscription" redirect so the user can land on this page to pick a
    higher/lower tier from the manage page's "Upgrade Your Plan" CTA.
    Without that bypass the manage page CTA would loop back to itself:
    manage -> plans -> (already subscribed) -> manage -> plans -> ...
    """
    user = request.user

    # Get user's current subscription if exists
    current_subscription = None
    current_store = None
    upgrade_mode = request.GET.get("upgrade") in ("1", "true", "yes")

    # Resolve the live subscription (used by both the early redirect and
    # the page render so we don't query twice).
    from apps.subscriptions.services import resolve_user_subscription

    live_subscription = resolve_user_subscription(user)
    has_live_subscription = (
        live_subscription is not None
        and getattr(live_subscription, "is_active", lambda: False)()
    )
    if live_subscription is not None:
        current_subscription = live_subscription

    # Check if the user already has any active store memberships. The
    # previous version used ``active_memberships(None)`` directly, but
    # that helper builds ``StoreMembership.objects.filter(store=None, ...)``
    # which in practice matches zero rows (every membership has a non-null
    # ``store_id``) — so the redirect-to-dashboard guard never fired and
    # users on an existing subscription saw the plans page unexpectedly.
    # Query the membership table explicitly with an active filter to
    # detect "user already has stores" reliably.
    from apps.permissions.models import StoreMembership

    has_active_memberships = StoreMembership.objects.filter(
        user=user,
        is_active=True,
    ).exists()

    # Only redirect existing users away from this page when they're NOT
    # explicitly asking to view plans for an upgrade. The ``?upgrade=1``
    # bypass is what the manage page's "Upgrade Your Plan" CTA relies on
    # — without it the button loops back to manage -> plans -> manage.
    if has_active_memberships and not upgrade_mode:
        # User already has access to stores → send them to the manage
        # page where they can upgrade/downgrade their live subscription
        # instead of presenting first-time-signup plans.
        return redirect("subscriptions:manage")

    # User paid for a plan but hasn't created their first store yet.
    # Send them to welcome so they can finish onboarding instead of
    # seeing the plans page again and being unsure what to do next.
    # Don't redirect when in upgrade mode — that flow is for users who
    # already have stores, so the "pending plan" funnel doesn't apply.
    if not upgrade_mode:
        pending_plan_slug = (
            getattr(user, "pending_plan_slug", None)
            or request.session.get("pending_plan_slug")
        )
        if pending_plan_slug:
            return redirect("subscriptions:welcome")

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
        "upgrade_mode": upgrade_mode,
        "live_subscription": live_subscription,
        "has_live_subscription": has_live_subscription,
    }

    return render(request, "subscriptions/plans.html", context)


@login_required
def subscription_checkout(request, plan_slug):
    """
    Handle subscription checkout process.

    For first-time signup (no real subscription yet) this records the
    plan choice on the user as a ``pending_plan_slug`` marker and
    redirects to the welcome page so the user can finish onboarding by
    creating their first store.

    For existing users (with a real ``Tenant.subscription`` already) the
    ``pending_plan_slug`` path used to be a no-op: it set the marker but
    never actually upgraded the live subscription, so once the user
    clicked "Go to Dashboard" they saw the OLD plan's limits. The fix
    is to apply the change immediately through the standard
    ``change_plan`` service when a live subscription exists, which
    invalidates caches and bumps RBAC versions atomically with the
    subscription row update. The user is then sent to the welcome page
    (so the same "Add Another Store / Go to Dashboard" affordances are
    shown), and any subsequent reads reflect the new plan.

    Re-subscribe path: a user whose subscription has been *canceled*
    (``status='canceled'``) still owns the row in the DB. The previous
    version of this view resolved ``resolve_user_subscription(user)``,
    which deliberately hides canceled rows; ``has_live_subscription``
    was then False, and the view fell into the first-time-signup branch
    — writing ``pending_plan_slug`` and redirecting to /welcome/ while
    the existing row stayed canceled. After re-subscribing, the user
    saw the dashboard's "subscription needs attention" banner, every
    gated write path 403-ing, and ``/filter`` reporting ``max_seats:
    null`` because ``get_active_subscription`` returns None. The fix
    is to look up the user's *row* (regardless of state) via
    ``find_user_subscription_row`` and route through ``change_plan``
    whenever one exists. ``change_plan`` itself detects the canceled
    state and reactivates the row (clearing ``ends_at``, flipping
    status back to ``active``, recording ``EVENT_REACTIVATED``) so the
    user lands on a live subscription after the redirect.
    """
    user = request.user

    try:
        plan = SubscriptionPlan.objects.get(slug=plan_slug, is_active=True)
    except SubscriptionPlan.DoesNotExist:
        return redirect("subscriptions:plans")

    # Resolve the user's *row* (regardless of state) once. We prefer
    # ``find_user_subscription_row`` over ``resolve_user_subscription``
    # here because the latter hides canceled / expired rows — exactly
    # the rows we want to revive when the user re-subscribes after a
    # cancel.
    from .services import (
        resolve_user_subscription,
        find_user_subscription_row,
        change_plan,
    )
    from django.utils import timezone
    from django.contrib import messages as dj_messages

    existing_subscription = find_user_subscription_row(user)
    has_existing_row = existing_subscription is not None

    # Whether the existing row is *live* (active / trialing / scheduled
    # cancel) determines whether we treat this as a plan upgrade vs a
    # full re-subscription. ``change_plan`` handles both: a live row
    # gets ``plan`` flipped, a canceled/expired row gets reactivated.
    live_subscription = (
        existing_subscription
        if has_existing_row
        and getattr(existing_subscription, "is_active", lambda: False)()
        else None
    )
    has_live_subscription = live_subscription is not None
    # The single dispatch predicate used in the POST handler below.
    # ``has_existing_row`` is the source of truth — even a canceled
    # row is still the user's subscription, so we route through
    # ``change_plan`` rather than the first-time-signup branch.
    should_change_plan = has_existing_row

    # Handle POST - either upgrade an existing sub in place, or record
    # the pending marker for first-time signup.
    if request.method == "POST":
        start_trial = request.POST.get("start_trial", "true").lower() == "true"

        if should_change_plan and existing_subscription is not None:
            # Apply the plan change immediately through the standard
            # service. ``change_plan`` handles upgrade/downgrade
            # dispatch, reactivation of canceled/expired rows, cache
            # invalidation, and ``pending_plan_slug`` clearing (see
            # Fix 4 in ``apps/subscriptions/services.py``).
            try:
                change_plan(
                    existing_subscription,
                    plan,
                    actor=user,
                    effective_immediately=True,
                )
            except ValueError:
                # Same price tier — degenerate case, just send the
                # user to manage so they can pick a different plan.
                dj_messages.warning(
                    request,
                    "The selected plan is the same as your current plan.",
                )
                return redirect("subscriptions:manage")

            # Success copy depends on the prior state. Upgrading a live
            # row says "upgraded"; reviving a canceled row says
            # "subscribed" (or "reactivated" when the user is picking
            # the same plan they had before the cancel).
            if has_live_subscription:
                success_action = "upgraded"
                success_message = f"Subscription upgraded to {plan.name}."
            elif existing_subscription.plan_id == plan.id:
                success_action = "reactivated"
                success_message = (
                    f"Subscription reactivated on {plan.name}."
                )
            else:
                success_action = "subscribed"
                success_message = (
                    f"Subscribed to {plan.name}."
                )
            dj_messages.success(request, success_message)

            # Drop the pending marker too in case it was set from a
            # prior (now-irrelevant) checkout attempt.
            from .services import clear_pending_plan_marker

            clear_pending_plan_marker(user, request)

            # ``change_plan`` itself clears the marker, but the request
            # session may still hold legacy ``subscription_plan`` /
            # ``pending_plan_*`` keys that the welcome view consumes;
            # wipe those so we don't double-render a "you picked this
            # plan" banner on the next page load.
            for key in (
                "subscription_plan",
                "trial_days",
                "pending_plan_slug",
                "pending_plan_name",
                "pending_trial",
            ):
                request.session.pop(key, None)

            # Send the user through the welcome page so the same
            # "Add Another Store / Go to Dashboard" affordances show
            # up — with the new plan name already applied to the live
            # subscription, the welcome banner correctly reflects it.
            request.session["plan_changed_just_now"] = {
                "action": success_action,
                "plan_name": plan.name,
                "plan_slug": plan.slug,
                "effective_immediately": True,
            }
            return redirect("subscriptions:welcome")

        # First-time-signup path: persist the pending marker and let the
        # welcome page collect enough info to create the first store.
        # ``apply_pending_plan`` will pick this marker up on store
        # creation and route through the same change_plan path.
        user.pending_plan_slug = plan.slug
        user.pending_trial_start = start_trial
        user.pending_subscription_date = timezone.now()
        user.save(
            update_fields=[
                "pending_plan_slug",
                "pending_trial_start",
                "pending_subscription_date",
            ]
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
    # If the user already has a live subscription the checkout form
    # doesn't make sense (they should go through ``/manage/`` instead),
    # but we still render the page so a direct link doesn't 404 — the
    # template context can warn the user.
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
        "has_live_subscription": has_live_subscription,
        "live_subscription": live_subscription,
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

    # Get available upgrade/downgrade plans.
    #
    # We restrict the candidates to plans that share the current plan's
    # billing period AND currency, then split by price. Comparing across
    # billing periods (e.g. monthly vs yearly) or currencies (BDT vs USD)
    # produces meaningless upgrade/downgrade choices:
    #   * A yearly BDT 48000 plan would dominate the "upgrade" list over
    #     a monthly BDT 99 plan even though they aren't really comparable.
    #   * A free USD $0 test/debug row would show as a "downgrade" for a
    #     Professional BDT 99 plan — currency-wrong and almost certainly
    #     an internal/leftover plan.
    #
    # Restricting to (billing_period, currency) matches the user's
    # intent ("upgrade my *current* plan") and prevents leftover test
    # rows with anomalous price/currency values from polluting the UI.
    current_plan = subscription.plan
    available_plans = (
        SubscriptionPlan.objects.filter(
            is_active=True,
            is_public=True,
            billing_period=current_plan.billing_period,
            currency=current_plan.currency,
        )
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
        # Cancellation-scheduled state (drives the banner + Reactivate
        # card on the manage page). ``is_canceled_or_canceling`` is the
        # broad predicate that covers *every* cancel path — scheduled
        # cancel (``status='active' + ends_at``) and immediate cancel
        # (``status='canceled'``). The narrower ``is_cancel_scheduled``
        # stays the gate for the Reactivate button, since reversing a
        # fully-canceled sub needs a different service flow.
        "cancellation_scheduled": subscription.is_canceled_or_canceling(),
        "cancellation_ends_at": (
            subscription.ends_at if subscription.is_canceled_or_canceling() else None
        ),
        "is_cancel_scheduled": subscription.is_cancel_scheduled(),
        "is_immediate_cancel": (
            subscription.status == "canceled"
            and not subscription.is_cancel_scheduled()
        ),
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
def reactivate_subscription_view(request):
    """
    Reverse a previously-scheduled cancel-at-period-end.

    Mirrors the resolution logic in ``cancel_subscription_view``
    (lines 700-718): tenant-based first, store-based fallback for the
    legacy migration period. Idempotent — a reactivate call on a
    subscription that isn't currently scheduled to cancel is a 200
    no-op (see ``reactivate_subscription``), so the UI can safely
    retry on network blips without surfacing a confusing error.
    """
    user = request.user

    # Same resolution pattern as cancel_subscription_view.
    from apps.accounts.models import Tenant

    subscription = None
    try:
        tenant = Tenant.objects.filter(owner=user).first()
        if tenant and hasattr(tenant, "subscription") and tenant.subscription:
            subscription = tenant.subscription
    except Exception:
        pass

    if not subscription:
        memberships = active_memberships(None).filter(user=user)
        if memberships.exists():
            store = _resolve_current_store_for_user(request, user)
            if store:
                subscription = get_active_subscription(store)

    if not subscription:
        return Response(
            {"error": "No active subscription found"},
            status=status.HTTP_404_NOT_FOUND,
        )

    try:
        with transaction.atomic():
            reactivate_subscription(subscription, actor=user)
            return Response(
                {
                    "message": "Subscription reactivated successfully",
                    "status": subscription.status,
                    "ends_at": (
                        subscription.ends_at.isoformat()
                        if subscription.ends_at
                        else None
                    ),
                }
            )
    except Exception as e:
        # Re-raise RBAC exceptions so DRF's EXCEPTION_HANDLER can map
        # them to a structured response (matches the pattern in
        # ``update_subscription_plan`` for DowngradeOverCapacity).
        from apps.permissions.exceptions import RBACError

        if isinstance(e, RBACError):
            raise
        return Response(
            {"error": str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def update_subscription_plan(request):
    """
    Upgrade or downgrade subscription plan.
    Updated for tenant-based architecture.

    Re-subscribe path: a user whose subscription has been *canceled*
    still owns the row in the DB. The previous version of this view
    used ``tenant.subscription`` (the reverse OneToOne on
    ``Subscription.tenant``) and ``get_active_subscription(store)`` as
    fallbacks — both return ``None`` / fail-open for canceled rows.
    After a cancel, the view responded 404 "No active subscription
    found" even though the user's row was right there, ready to be
    revived.

    The fix is to use ``find_user_subscription_row`` which returns the
    user's most-recent row regardless of state. ``change_plan`` then
    detects the canceled state and reactivates the row before the
    upgrade/downgrade dispatch. Endpoint behaviour is identical for
    live rows; only the cancel-then-resubscribe path needed widening.
    """
    serializer = SubscriptionUpdateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user = request.user

    # Resolve the user's *row* regardless of state. ``resolve_user_subscription``
    # would hide canceled/expired rows; that's the wrong tool here
    # because the user is about to flip status back to active.
    from .services import find_user_subscription_row

    subscription = find_user_subscription_row(user)

    if not subscription:
        return Response({"error": "No subscription found"}, status=status.HTTP_404_NOT_FOUND)

    # If the resolved sub is still attached to a single legacy store
    # (no tenant FK), promote it to a tenant sub before we mutate ``plan``.
    # Without this the new plan only takes effect for a *new* store under
    # the eventual tenant — the existing store keeps reading the old plan
    # via the legacy fallback in ``get_active_subscription``.
    if subscription.tenant_id is None:
        target_store = (
            subscription.store
            if subscription.store_id
            else _resolve_current_store_for_user(request, user)
        )
        if target_store is not None:
            promote_subscription_to_tenant(subscription, target_store)

    try:
        new_plan = SubscriptionPlan.objects.get(
            slug=serializer.validated_data["new_plan_slug"], is_active=True
        )
    except SubscriptionPlan.DoesNotExist:
        return Response({"error": "Plan not found"}, status=status.HTTP_404_NOT_FOUND)

    try:
        with transaction.atomic():
            effective_immediately = serializer.validated_data["effective_immediately"]
            # Capture direction *before* ``change_plan`` mutates
            # ``subscription.plan`` so the success-banner logic doesn't
            # need to know the previous price.
            if new_plan.price > subscription.plan.price:
                action = "upgraded"
            elif new_plan.price < subscription.plan.price:
                action = "downgraded"
            else:
                return Response(
                    {"error": "Cannot switch to same price plan"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            subscription = change_plan(
                subscription,
                new_plan,
                actor=user,
                effective_immediately=effective_immediately,
            )

            # The user's pending_plan_slug is a one-shot signup marker. It
            # would otherwise stay set indefinitely after this plan change,
            # silently polluting the aggregated-limits / stats endpoints
            # (those reads treat pending_plan_slug as the upper bound when
            # it is larger than the live plan). clearing it here keeps the
            # marker and the live subscription in sync.
            from .services import clear_pending_plan_marker

            clear_pending_plan_marker(user, request)

            request.session["plan_changed_just_now"] = {
                "action": action,
                "plan_name": new_plan.name,
                "plan_slug": new_plan.slug,
                "effective_immediately": (
                    action == "upgraded" or effective_immediately
                ),
            }

            return Response(
                {
                    "message": f"Subscription {action} successfully",
                    "plan": new_plan.name,
                    "status": subscription.status,
                }
            )

    except ValueError:
        return Response(
            {"error": "Cannot switch to same price plan"},
            status=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        # Re-raise RBAC exceptions (notably ``DowngradeOverCapacity``) so
        # DRF's ``EXCEPTION_HANDLER`` can produce the structured 400
        # response. Catching them here would mask the structured payload
        # and degrade the user-facing modal to a generic 500.
        from apps.permissions.exceptions import RBACError
        if isinstance(e, RBACError):
            raise
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
