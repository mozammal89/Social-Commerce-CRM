"""
Subscription services for managing subscription lifecycle and operations.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, TYPE_CHECKING

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone
from django.core.cache import cache

if TYPE_CHECKING:
    from apps.accounts.models import Tenant

from .constants import (
    STATUS_TRIALING,
    STATUS_ACTIVE,
    STATUS_PAST_DUE,
    STATUS_CANCELED,
    STATUS_EXPIRED,
    EVENT_CREATED,
    EVENT_TRIAL_STARTED,
    EVENT_PAYMENT_SUCCEEDED,
    EVENT_PAYMENT_FAILED,
    EVENT_RENEWED,
    EVENT_UPGRADED,
    EVENT_DOWNGRADED,
    EVENT_CANCELED,
    EVENT_EXPIRED,
    EVENT_REACTIVATED,
    EVENT_PLAN_CHANGED,
    VALID_STATUS_TRANSITIONS,
    DEFAULT_TRIAL_DAYS,
    CACHE_SUBSCRIPTION_PREFIX,
    CACHE_PLAN_PREFIX,
    CACHE_KEY_TIMEOUT,
)
from .exceptions import (
    PlanLimitExceeded,
    SubscriptionInactiveError,
    PlanNotFoundError,
    SubscriptionAlreadyExistsError,
    TransitionNotAllowedError,
    TrialExpiredError,
)
from apps.permissions.models import (
    Subscription,
    SubscriptionPlan,
    SubscriptionEvent,
    StoreMembership,
)
from apps.stores.models import Store

logger = logging.getLogger(__name__)


def record_event(
    subscription: Subscription, event_type: str, *, actor=None, metadata: Dict[str, Any] = None
) -> SubscriptionEvent:
    """
    Record a subscription event with metadata.

    Args:
        subscription: The subscription instance
        event_type: The type of event being recorded
        actor: The user who triggered the event (if applicable)
        metadata: Additional event metadata

    Returns:
        The created SubscriptionEvent instance
    """
    return SubscriptionEvent.objects.create(
        subscription=subscription,
        event_type=event_type,
        occurred_at=timezone.now(),
        actor=actor,
        metadata=metadata or {},
    )


def validate_status_transition(current_status: str, new_status: str) -> bool:
    """
    Validate if a status transition is allowed.

    Args:
        current_status: Current subscription status
        new_status: Target status

    Returns:
        True if transition is valid, False otherwise
    """
    allowed_transitions = VALID_STATUS_TRANSITIONS.get(current_status, [])
    return new_status in allowed_transitions


def transition_status(
    subscription: Subscription,
    new_status: str,
    *,
    actor=None,
    reason: str = None,
    metadata: Dict[str, Any] = None,
) -> bool:
    """
    Move a subscription to a new status with event logging.

    Args:
        subscription: The subscription to transition
        new_status: The target status
        actor: The user triggering the transition
        reason: Reason for the transition
        metadata: Additional transition metadata

    Returns:
        True if status was changed, False if already at target status

    Raises:
        TransitionNotAllowedError: If transition is not valid
    """
    if subscription.status == new_status:
        return False

    if not validate_status_transition(subscription.status, new_status):
        raise TransitionNotAllowedError(subscription.status, new_status)

    old_status = subscription.status
    subscription.status = new_status

    # Map transitions to canonical event types
    transition = (old_status, new_status)
    event_type_map = {
        (STATUS_TRIALING, STATUS_ACTIVE): EVENT_PAYMENT_SUCCEEDED,
        (STATUS_TRIALING, STATUS_CANCELED): EVENT_CANCELED,
        (STATUS_TRIALING, STATUS_EXPIRED): EVENT_EXPIRED,
        (STATUS_ACTIVE, STATUS_PAST_DUE): EVENT_PAYMENT_FAILED,
        (STATUS_ACTIVE, STATUS_CANCELED): EVENT_CANCELED,
        (STATUS_ACTIVE, STATUS_EXPIRED): EVENT_EXPIRED,
        (STATUS_PAST_DUE, STATUS_ACTIVE): EVENT_RENEWED,
        (STATUS_PAST_DUE, STATUS_CANCELED): EVENT_CANCELED,
        (STATUS_PAST_DUE, STATUS_EXPIRED): EVENT_EXPIRED,
        (STATUS_CANCELED, STATUS_ACTIVE): EVENT_REACTIVATED,
    }

    event_type = event_type_map.get(transition, f"transition.{old_status}_to_{new_status}")

    payload = {"from": old_status, "to": new_status}
    if reason:
        payload["reason"] = reason
    if metadata:
        payload.update(metadata)

    subscription.save(update_fields=["status", "updated_at"])
    record_event(subscription, event_type, actor=actor, metadata=payload)

    # Clear subscription cache
    cache.delete(f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.store_id}")

    logger.info(f"Subscription {subscription.id} transitioned from {old_status} to {new_status}")
    return True


def promote_subscription_to_tenant(
    subscription: Subscription,
    store: Store,
) -> Subscription:
    """Promote a legacy store-level Subscription to a tenant-level one in-place.

    During the cutover from per-store to per-tenant subscriptions, some
    users still hold a ``Subscription`` row whose ``store`` FK is set and
    ``tenant`` is NULL. When that user upgrades, we update the row's
    ``plan`` but ``get_active_subscription(store)`` reads it via the
    tenant path and returns nothing — so the new limits look like they
    didn't take effect for the *existing* store.

    This helper bridges that gap: if the row is store-only and the store
    has a tenant, attach the row to the tenant and clear the store FK.
    The next ``get_active_subscription`` for any store under that tenant
    returns the upgraded row, and ``check_plan_limits`` takes the tenant
    branch (counting across all tenant stores).

    Idempotent and a no-op when ``subscription.tenant`` is already set or
    when the store has no tenant yet.
    """
    if subscription.tenant_id is not None:
        return subscription
    if store is None or store.tenant_id is None:
        return subscription

    subscription.tenant = store.tenant
    subscription.store = None
    subscription.save(update_fields=["tenant", "store", "updated_at"])

    # The row used to live at the store-keyed cache slot; evict it so the
    # next ``get_active_subscription(store)`` falls through to the tenant
    # branch instead of returning the now-detached old instance.
    cache.delete(f"{CACHE_SUBSCRIPTION_PREFIX}{store.id}")
    return subscription


def get_or_create_default_tenant(user) -> "Tenant":
    """Return the user's primary ``Tenant``, creating one if missing.

    Every user on the platform should own a single workspace tenant.
    Pre-tenant signup flows (legacy store-only users) don't have one
    yet; this helper materialises a sensible default so subsequent
    store-creation and subscription code can rely on the invariant.

    Resolution order:

      1. An existing tenant the user already owns (looked up by
         ``owner=user``). This catches the common case where the user
         was created via a different flow — tests, the dashboard's
         tenant-creation middleware, or a custom signup that picked a
         different slug — without forcing us to match its slug.
      2. A tenant with the email-derived ``<local>-workspace`` slug.
         Used by the standard signup flow; ``get_or_create`` makes it
         idempotent so two concurrent calls (e.g. the signup API and
         the dashboard's tenant-resolution middleware) don't race into
         IntegrityError.
    """
    from apps.accounts.models import Tenant

    # First pass: any tenant this user already owns. Picking this up
    # before the slug lookup means an existing tenant with a custom
    # slug (e.g. created by tests or by the dashboard's tenant-creation
    # middleware) is reused instead of producing a second, orphan
    # workspace for the same user.
    owned = Tenant.objects.filter(owner=user, is_active=True).first()
    if owned is not None:
        return owned

    slug = (
        f"{user.email.split('@')[0]}-workspace"
        if user.email
        else f"ws-{user.id}"
    )
    tenant, _ = Tenant.objects.get_or_create(
        slug=slug,
        defaults={
            "name": f"{user.get_full_name()}'s Workspace",
            "owner": user,
            "is_active": True,
        },
    )
    return tenant


def find_user_subscription_row(user):
    """Return the user's most recent ``Subscription`` row, regardless of
    status, or ``None`` if the user has never subscribed.

    Unlike ``resolve_user_subscription`` — which deliberately hides
    terminal-state rows (``canceled`` / ``expired`` / ``past_due``)
    because those should look like "no subscription" to the dashboard
    and write-path gates — this helper is the reactivation / re-engage
    lookup. The checkout flow and the in-place plan-update API use it
    to find a row that can be revived by ``change_plan``; the dashboard
    uses ``resolve_user_subscription`` to decide whether to render the
    "subscription needs attention" banner. The two lookups must
    coexist: one hides canceled rows from the UI, the other finds
    them so a fresh plan choice actually reactivates something.

    Resolution order mirrors ``resolve_user_subscription``:

      1. The user's tenant-level ``Subscription`` (if any) — including
         terminal-state rows, since the row is still "the user's".
      2. The most recent legacy per-store ``Subscription`` attached to
         one of the user's stores. We deliberately do *not* promote
         the row here (no side-effecting write); the caller decides
         whether promotion is appropriate.

    Returns the most-recent row by ``starts_at`` (and ``id`` to break
    ties deterministically). Selecting by ``starts_at`` rather than
    ``plan__price`` because for reactivation we want the row that
    actually exists in the user's account, not the most generous one
    — a user who downgraded from Pro to Starter still has the Starter
    row as "their" subscription.
    """
    tenant = get_or_create_default_tenant(user)

    tenant_sub = (
        Subscription.objects
        .filter(tenant=tenant)
        .order_by("-starts_at", "-id")
        .first()
    )
    if tenant_sub is not None:
        return tenant_sub

    legacy_sub = (
        Subscription.objects
        .filter(tenant__isnull=True)
        .filter(
            Q(store__tenant=tenant)
            | Q(store__memberships__user=user, store__memberships__is_active=True)
        )
        .distinct()
        .select_related("store", "plan")
        .order_by("-starts_at", "-id")
        .first()
    )
    return legacy_sub


def resolve_user_subscription(user):
    """Return the user's authoritative active subscription, or ``None``.

    Resolution order:

      1. The user's tenant-level ``Subscription`` (if any).
      2. The most generous legacy per-store ``Subscription`` attached
         to one of the user's stores. The legacy sub is *promoted* to
         the user's tenant so subsequent reads and writes see one
         consistent plan across every store.

    Returns ``None`` when the user has no active subscription at all
    (true first-time signup).

    A subscription with ``status='active'`` AND a future ``ends_at``
    (i.e. ``is_cancel_scheduled()`` is True) **is** considered active
    here — the user keeps full access until the period ends, so the
    sidebar's "Store Management" section, the dashboard's normal
    landing, and the rest of the app should all keep working. Only a
    truly terminal state (``status='canceled' / 'expired' / 'past_due'``
    without a scheduled cancel) is treated as "no subscription".
    """
    tenant = get_or_create_default_tenant(user)

    # First pass: any tenant-level sub that's active, trialing, or has
    # a future ``ends_at``. Using ``Q(status__in=...) | Q(ends_at__gt=...)``
    # rather than only ``status__in=[active, trialing]`` so a scheduled
    # cancel keeps the user on the normal UI.
    tenant_sub = (
        Subscription.objects
        .filter(tenant=tenant)
        .filter(
            Q(status__in=[STATUS_ACTIVE, STATUS_TRIALING])
            | Q(ends_at__gt=timezone.now())
        )
        .order_by("-plan__price", "-starts_at")
        .first()
    )
    if tenant_sub is not None:
        return tenant_sub

    # Join through ``store__tenant=tenant`` so we don't materialise the
    # store queryset in Python before issuing the sub query.
    # Fall back to stores owned by the user through active memberships
    # — covers legacy data where ``Store.tenant`` was never backfilled.
    legacy_sub = (
        Subscription.objects
        .filter(tenant__isnull=True)
        .filter(
            Q(status__in=[STATUS_ACTIVE, STATUS_TRIALING])
            | Q(ends_at__gt=timezone.now())
        )
        .filter(
            Q(store__tenant=tenant)
            | Q(store__memberships__user=user, store__memberships__is_active=True)
        )
        .distinct()
        .select_related("store", "plan")
        .order_by("-plan__price", "-starts_at")
        .first()
    )
    if legacy_sub is None:
        return None

    # Promote in place so subsequent reads resolve through the tenant
    # branch. If the store has no tenant yet, attach the freshly-resolved
    # one so ``promote_subscription_to_tenant`` has somewhere to anchor.
    if legacy_sub.store_id is not None and legacy_sub.store.tenant_id is None:
        legacy_sub.store.tenant = tenant
        legacy_sub.store.save(update_fields=["tenant", "updated_at"])
    promote_subscription_to_tenant(legacy_sub, legacy_sub.store)
    return legacy_sub


def change_plan(
    subscription: Subscription,
    new_plan: SubscriptionPlan,
    *,
    actor=None,
    effective_immediately: bool = False,
) -> Subscription:
    """Apply a plan change to ``subscription``, dispatching on price.

    The two callers (``update_subscription_plan`` API and the
    store-create flow's pending-plan branch) used to inline the same
    ``if price > else downgrade`` ladder. Centralising the dispatch
    here keeps both call sites to a single line and ensures the cache
    invalidation logic in ``upgrade_subscription`` /
    ``downgrade_subscription`` runs in both paths.

    After a successful change, ``actor.pending_plan_slug`` is cleared
    so that subsequent reads (aggregated-limits, create-store, team
    stats) can't surface the stale one-shot signup marker as the
    "current plan". ``apply_pending_plan`` already cleared it for its
    own signup-driven path; this is the belt-and-braces mirror for
    explicit in-place upgrades/downgrades.

    Re-activation guard: when the source subscription is in a terminal
    ``expired`` state (e.g. the 14-day trial lapsed and the user is now
    picking a paid plan) **or** an immediate ``canceled`` state (the
    user cancelled with ``cancel_at_period_end=False`` and is now
    re-subscribing to a fresh plan), ``upgrade_subscription`` and
    ``downgrade_subscription`` would otherwise flip ``plan`` but leave
    ``status='expired'`` / ``status='canceled'``. ``is_active()`` would
    keep returning False and the user would be stuck on the redirect
    loop between ``/subscriptions/manage/`` and ``/subscriptions/plans/``
    — every gated write path (invite members, create roles, set
    overrides) would still 403 because the subscription gate reads
    ``is_active()``.

    For ``expired``, ``VALID_STATUS_TRANSITIONS`` blocks any transition
    out of ``expired``; we reset status to ``active`` and clear
    ``trial_ends_at`` before the dispatch so the row is alive by the
    time ``upgrade_subscription`` writes ``plan``.

    For ``canceled``, the user keeps ``status='canceled'`` until either
    the period ends naturally *or* they explicitly re-engage. Picking a
    new plan is the explicit re-engagement — flip status to ``active``
    and clear any leftover ``ends_at`` (a cancel-at-period-end that was
    scheduled but not yet elapsed) before dispatching. The audit log
    records the reason so we can tell reactivation-after-cancel apart
    from the normal plan-change flow.

    For the ``active + ends_at-future`` case (a scheduled cancel that
    hasn't yet elapsed), ``is_active()`` already returns True, so the
    write paths aren't blocked — but the Reactivate banner would keep
    rendering on the manage page after the user picks a fresh plan.
    Clearing ``ends_at`` here makes the row match the user's intent
    ("I'm back to a fresh subscription").
    """
    needs_reactivate = (
        subscription.status in (STATUS_EXPIRED, STATUS_CANCELED)
        or subscription.ends_at is not None
    )
    if needs_reactivate:
        previous_status = subscription.status
        previous_ends_at = subscription.ends_at
        was_terminal = previous_status in (STATUS_EXPIRED, STATUS_CANCELED)
        if was_terminal:
            subscription.status = STATUS_ACTIVE
        # Clear the scheduled-cancel clock so the row reflects a clean
        # re-subscription, not a still-terminating one. ``ends_at`` is
        # nullable; ``trial_ends_at`` is only relevant when we came
        # from ``expired``, but resetting both is harmless.
        subscription.ends_at = None
        subscription.trial_ends_at = None
        subscription.save(
            update_fields=["status", "ends_at", "trial_ends_at", "updated_at"],
        )
        # Audit only the cases where this is a *new* reactivation
        # event (terminal -> active). For "scheduled cancel just
        # cleared" we don't emit a reactivation event — the row never
        # stopped being active; the user just un-cancelled their
        # future termination.
        if was_terminal:
            record_event(
                subscription,
                EVENT_REACTIVATED,
                actor=actor,
                metadata={
                    "reason": (
                        "plan_change_after_expiry"
                        if previous_status == STATUS_EXPIRED
                        else "plan_change_after_cancel"
                    ),
                    "previous_status": previous_status,
                    "new_plan": new_plan.slug,
                },
            )
        elif previous_ends_at is not None:
            record_event(
                subscription,
                EVENT_REACTIVATED,
                actor=actor,
                metadata={
                    "reason": "cancel_reversed_by_plan_change",
                    "previous_ends_at": (
                        previous_ends_at.isoformat()
                        if previous_ends_at else None
                    ),
                    "new_plan": new_plan.slug,
                },
            )
        # Evict tenant/store sub caches so the next read picks up the
        # freshly-active row (the upgrade/downgrade helpers below also
        # evict, but doing it here keeps observers consistent for any
        # intermediate caller that only re-checks ``is_active()``).
        keys_to_evict: list[str] = []
        if subscription.tenant_id:
            keys_to_evict.append(
                f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.tenant_id}"
            )
        if subscription.store_id:
            keys_to_evict.append(
                f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.store_id}"
            )
        if keys_to_evict:
            cache.delete_many(keys_to_evict)

    if new_plan.price > subscription.plan.price:
        result = upgrade_subscription(subscription, new_plan, actor=actor)
    elif new_plan.price < subscription.plan.price:
        result = downgrade_subscription(
            subscription,
            new_plan,
            actor=actor,
            effective_at_period_end=not effective_immediately,
        )
    else:
        raise ValueError(
            f"Cannot change to plan {new_plan.slug}: same price as current "
            f"plan {subscription.plan.slug}."
        )

    if actor is not None:
        clear_pending_plan_marker(actor)

    return result


def propagate_plan_to_all_user_stores(
    subscription: Subscription,
    *,
    actor=None,
) -> None:
    """Apply a plan change to every store the actor owns.

    Mirrors ``consolidate_user_subscriptions`` for the live upgrade /
    downgrade path. Multi-store tenants that grew up during the
    legacy-per-store era often hold one ``Subscription`` per store, each
    with its own plan. Upgrading only the *current* store's sub leaves
    the other stores on the old plan — the user sees Store A at the
    new cap while Store B is still stuck at the old one. Running the
    management command fixed that for data already in this state; this
    helper prevents new occurrences by sweeping after every plan change.

    Steps:

    1. Resolve the tenant. If the upgraded sub is still store-only,
       materialise a tenant and bind the sub's store to it; the caller
       has already updated ``subscription.plan`` in the same
       transaction so this just plumbs the tenant plumbing.
    2. Attach every other store the actor owns (active memberships) to
       the same tenant so plan limits become tenant-scoped.
    3. Cancel any other legacy per-store ``Subscription`` rows that
       belong to those stores — they're stale duplicates of the
       upgraded one.
    4. Evict every cache slot that might still hold the old plan:
       per-tenant, per-store-keyed (legacy), and the plan-keyed slots.

    No-op when the actor has only one store (no consolidation needed)
    or when the upgraded sub is already tenant-attached and the user
    has no legacy duplicates.
    """
    from django.db import transaction as _tx

    from apps.stores.models import Store

    target_user = actor if actor is not None else (
        subscription.store.owners.first() if subscription.store_id else None
    )
    if target_user is None:
        return

    user_store_ids = list(
        Store.objects.filter(
            memberships__user=target_user,
            memberships__is_active=True,
            is_deleted=False,
        ).distinct().values_list("id", flat=True)
    )
    if not user_store_ids:
        return

    # Resolve / create the tenant. If the upgraded sub is still store-only,
    # use ``get_or_create_default_tenant`` so the row has somewhere to anchor.
    if subscription.tenant_id is not None:
        tenant_id = subscription.tenant_id
    else:
        tenant = get_or_create_default_tenant(target_user)
        tenant_id = tenant.id
        # If the sub is still store-attached, bind its store to the tenant
        # first so ``promote_subscription_to_tenant`` has somewhere to
        # anchor (it no-ops when ``store.tenant_id`` is None).
        if subscription.store_id is not None:
            Store.objects.filter(
                id=subscription.store_id, tenant__isnull=True,
            ).update(tenant_id=tenant_id)
            # Refresh so promote sees the new tenant FK.
            subscription.refresh_from_db()
            promote_subscription_to_tenant(subscription, subscription.store)
        else:
            subscription.tenant_id = tenant_id
            subscription.save(update_fields=["tenant", "updated_at"])

    # Cancel any other active per-store subs the user owns. These are
    # duplicates left behind by the legacy per-store subscription era.
    # ``tenant__isnull=True`` keeps the just-upgraded (now tenant-attached)
    # sub out of the cancel set, and ``exclude(id=subscription.id)`` is a
    # belt-and-braces guard for the same sub id.
    with _tx.atomic():
        Store.objects.filter(id__in=user_store_ids).update(tenant_id=tenant_id)

        duplicate_ids = list(
            Subscription.objects
            .filter(
                store_id__in=user_store_ids,
                tenant__isnull=True,
                status__in=[STATUS_ACTIVE, STATUS_TRIALING],
            )
            .exclude(id=subscription.id)
            .values_list("id", flat=True)
        )
        if duplicate_ids:
            Subscription.objects.filter(id__in=duplicate_ids).update(
                status=STATUS_CANCELED,
            )

    # Evict every cache slot that could still hold the pre-change sub.
    keys = [
        f"{CACHE_SUBSCRIPTION_PREFIX}{tenant_id}",
        f"{CACHE_PLAN_PREFIX}{subscription.plan.slug}",
    ]
    keys.extend(f"{CACHE_SUBSCRIPTION_PREFIX}{sid}" for sid in user_store_ids)
    cache.delete_many(keys)


def clear_pending_plan_marker(user, request=None) -> None:
    """Reset the ``pending_plan_slug`` marker on ``user`` (and session).

    Called after a pending plan has been applied to a real
    subscription so the next store creation doesn't try to re-apply
    it. Safe to call when no pending marker is set.
    """
    if getattr(user, "pending_plan_slug", None):
        user.pending_plan_slug = None
        user.pending_trial_start = False
        user.pending_subscription_date = None
        user.save(
            update_fields=[
                "pending_plan_slug",
                "pending_trial_start",
                "pending_subscription_date",
            ],
        )
    if request is not None and hasattr(request, "session"):
        request.session.pop("pending_plan_slug", None)
        request.session.pop("pending_plan_name", None)
        request.session.pop("pending_trial", None)


def apply_pending_plan(
    user,
    *,
    store: Store,
    request=None,
) -> Optional[Subscription]:
    """Apply the user's pending plan to their real subscription.

    Reads ``user.pending_plan_slug`` (or the session fallback) and
    routes the change through the standard ``change_plan`` service so
    the same cache invalidation runs whether the user is signing up
    their first store or upgrading mid-flight. The pending marker is
    cleared on success.

    Returns the updated ``Subscription`` (or the freshly-created one
    for first-time signup) or ``None`` when no pending plan was set
    or the named plan no longer exists.
    """
    pending_plan_slug = (
        getattr(user, "pending_plan_slug", None)
        or (request.session.get("pending_plan_slug") if request else None)
    )
    if not pending_plan_slug:
        return None

    try:
        plan = SubscriptionPlan.objects.get(slug=pending_plan_slug, is_active=True)
    except SubscriptionPlan.DoesNotExist:
        clear_pending_plan_marker(user, request)
        return None

    existing = resolve_user_subscription(user)

    if existing is not None:
        # First-time-signup is impossible here (a sub already exists),
        # so the only sensible action is plan change.
        if plan.id != existing.plan_id:
            change_plan(
                existing, plan, actor=user, effective_immediately=True,
            )
    else:
        # First store, no prior sub — create a tenant-attached trial /
        # paid sub. Use the legacy per-store creators and then
        # promote, so we exercise the same code path that already
        # handles trial-day setup and Stripe field bookkeeping.
        pending_trial = bool(getattr(user, "pending_trial_start", False))
        if not pending_trial and request is not None:
            pending_trial = bool(request.session.get("pending_trial", True))
        if pending_trial and plan.trial_days and plan.trial_days > 0:
            new_sub = create_trial_subscription(
                store, plan, actor=user, trial_days=plan.trial_days,
            )
        else:
            new_sub = create_paid_subscription(store, plan, actor=user)
        promote_subscription_to_tenant(new_sub, store)
        existing = new_sub

    clear_pending_plan_marker(user, request)
    return existing


def create_trial_subscription(
    store: Store,
    plan: SubscriptionPlan,
    *,
    actor=None,
    trial_days: int = None,
    metadata: Dict[str, Any] = None,
) -> Subscription:
    """
    Create a new trial subscription for a store.

    Args:
        store: The store to create subscription for
        plan: The subscription plan to use
        actor: The user creating the subscription
        trial_days: Number of trial days (defaults from plan)
        metadata: Additional subscription metadata

    Returns:
        The created Subscription instance

    Raises:
        SubscriptionAlreadyExistsError: If store already has active subscription
    """
    if hasattr(store, "subscription") and store.subscription:
        if store.subscription.is_active():
            raise SubscriptionAlreadyExistsError(store.id)

    trial_duration = trial_days or plan.trial_days or DEFAULT_TRIAL_DAYS
    now = timezone.now()

    subscription = Subscription.objects.create(
        store=store,
        plan=plan,
        status=STATUS_TRIALING,
        starts_at=now,
        trial_ends_at=now + timedelta(days=trial_duration),
    )

    record_event(subscription, EVENT_TRIAL_STARTED, actor=actor, metadata=metadata or {})

    logger.info(f"Created trial subscription {subscription.id} for store {store.id}")
    return subscription


def create_paid_subscription(
    store: Store,
    plan: SubscriptionPlan,
    *,
    payment_gateway_id: str = None,
    customer_id: str = None,
    billing_period_start: datetime = None,
    billing_period_end: datetime = None,
    actor=None,
    metadata: Dict[str, Any] = None,
) -> Subscription:
    """
    Create a new paid subscription for a store.

    Args:
        store: The store to create subscription for
        plan: The subscription plan to use
        payment_gateway_id: Gateway subscription ID
        customer_id: Gateway customer ID
        billing_period_start: Start of billing period
        billing_period_end: End of billing period
        actor: The user creating the subscription
        metadata: Additional subscription metadata

    Returns:
        The created Subscription instance

    Raises:
        SubscriptionAlreadyExistsError: If store already has active subscription
    """
    if hasattr(store, "subscription") and store.subscription:
        if store.subscription.is_active():
            raise SubscriptionAlreadyExistsError(store.id)

    now = timezone.now()

    subscription = Subscription.objects.create(
        store=store,
        plan=plan,
        status=STATUS_ACTIVE,
        starts_at=now,
        current_period_start=billing_period_start or now,
        current_period_end=billing_period_end or (now + timedelta(days=30)),
        stripe_customer_id=customer_id or "",
        stripe_subscription_id=payment_gateway_id or "",
    )

    record_event(subscription, EVENT_CREATED, actor=actor, metadata=metadata or {})

    logger.info(f"Created paid subscription {subscription.id} for store {store.id}")
    return subscription


def create_trial_subscription_for_tenant(
    tenant: "Tenant",
    plan: SubscriptionPlan,
    *,
    actor=None,
    trial_days: int = None,
    metadata: Dict[str, Any] = None,
) -> Subscription:
    """
    Create a new trial subscription for a tenant.

    New tenant-based subscription creation for the refactored architecture.

    Args:
        tenant: The tenant to create subscription for
        plan: The subscription plan to use
        actor: The user creating the subscription
        trial_days: Number of trial days (defaults from plan)
        metadata: Additional subscription metadata

    Returns:
        The created Subscription instance

    Raises:
        SubscriptionAlreadyExistsError: If tenant already has active subscription
    """
    from apps.accounts.models import Tenant

    # Check if tenant already has an active subscription
    try:
        existing_subscription = Subscription.objects.get(tenant=tenant)
        if existing_subscription.is_active():
            raise SubscriptionAlreadyExistsError(tenant.id)
    except Subscription.DoesNotExist:
        pass

    trial_duration = trial_days or plan.trial_days or DEFAULT_TRIAL_DAYS
    now = timezone.now()

    subscription = Subscription.objects.create(
        tenant=tenant,
        plan=plan,
        status=STATUS_TRIALING,
        starts_at=now,
        trial_ends_at=now + timedelta(days=trial_duration),
    )

    record_event(subscription, EVENT_TRIAL_STARTED, actor=actor, metadata=metadata or {})

    logger.info(f"Created trial subscription {subscription.id} for tenant {tenant.id}")
    return subscription


def create_paid_subscription_for_tenant(
    tenant: "Tenant",
    plan: SubscriptionPlan,
    *,
    payment_gateway_id: str = None,
    customer_id: str = None,
    billing_period_start: datetime = None,
    billing_period_end: datetime = None,
    actor=None,
    metadata: Dict[str, Any] = None,
) -> Subscription:
    """
    Create a new paid subscription for a tenant.

    New tenant-based subscription creation for the refactored architecture.

    Args:
        tenant: The tenant to create subscription for
        plan: The subscription plan to use
        payment_gateway_id: Gateway subscription ID
        customer_id: Gateway customer ID
        billing_period_start: Start of billing period
        billing_period_end: End of billing period
        actor: The user creating the subscription
        metadata: Additional subscription metadata

    Returns:
        The created Subscription instance

    Raises:
        SubscriptionAlreadyExistsError: If tenant already has active subscription
    """
    from apps.accounts.models import Tenant

    # Check if tenant already has an active subscription
    try:
        existing_subscription = Subscription.objects.get(tenant=tenant)
        if existing_subscription.is_active():
            raise SubscriptionAlreadyExistsError(tenant.id)
    except Subscription.DoesNotExist:
        pass

    now = timezone.now()

    subscription = Subscription.objects.create(
        tenant=tenant,
        plan=plan,
        status=STATUS_ACTIVE,
        starts_at=now,
        current_period_start=billing_period_start or now,
        current_period_end=billing_period_end or (now + timedelta(days=30)),
        stripe_customer_id=customer_id or "",
        stripe_subscription_id=payment_gateway_id or "",
    )

    record_event(subscription, EVENT_CREATED, actor=actor, metadata=metadata or {})

    logger.info(f"Created paid subscription {subscription.id} for tenant {tenant.id}")
    return subscription


def cancel_subscription(
    subscription: Subscription,
    *,
    cancel_at_period_end: bool = False,
    actor=None,
    reason: str = None,
) -> Subscription:
    """
    Cancel an active subscription.

    Args:
        subscription: The subscription to cancel
        cancel_at_period_end: If True, cancel at period end; if False, cancel immediately
        actor: The user canceling the subscription
        reason: Reason for cancellation

    Returns:
        The updated Subscription instance
    """
    if cancel_at_period_end and subscription.status == STATUS_ACTIVE:
        # Resolve ``ends_at`` from ``current_period_end`` — but fall
        # back to a sensible default when the row has no
        # ``current_period_end`` set (legacy data, sub created before
        # the billing-period fields were required, or rows that were
        # imported without them). Without this fallback, ``ends_at``
        # would be ``None`` and ``Subscription.is_cancel_scheduled()``
        # would return False — the cancel API would return success
        # but the manage-page banner and Reactivate button would never
        # appear, leaving the user stuck with a Cancel button that's
        # still clickable and no visible state change after reload.
        #
        # The fallback mirrors ``renew_subscription`` and
        # ``create_paid_subscription``: ``now + 30 days`` is the
        # default billing period used everywhere else in this module.
        if subscription.current_period_end:
            subscription.ends_at = subscription.current_period_end
        else:
            anchor = (
                subscription.current_period_start
                or subscription.starts_at
                or timezone.now()
            )
            # If ``current_period_end`` was supposed to be 30 days
            # after the anchor (the default) and is in the past,
            # default to ``now + 30 days`` so the cancel banner
            # displays a meaningful future date. If the anchor is in
            # the future (e.g. a brand-new sub whose period hasn't
            # started yet), use ``anchor + 30 days`` so the cancel
            # date aligns with the rest of the period.
            fallback_end = anchor + timedelta(days=30)
            if fallback_end <= timezone.now():
                fallback_end = timezone.now() + timedelta(days=30)
            subscription.ends_at = fallback_end
        subscription.save(update_fields=["ends_at", "updated_at"])

        record_event(
            subscription,
            EVENT_CANCELED,
            actor=actor,
            metadata={"reason": reason, "cancel_at_period_end": True},
        )

        logger.info(f"Scheduled cancellation for subscription {subscription.id} at period end")
    else:
        transition_status(subscription, STATUS_CANCELED, actor=actor, reason=reason)

    # Evict the cached subscription slot(s) so the next read picks up
    # the updated ``ends_at`` (or ``status`` for immediate cancels).
    # Without this, downstream callers that use ``get_active_subscription``
    # — the dashboard's plan display, the team-management
    # ``/filter`` endpoint, ``plan_limit`` lookups, etc. — would see a
    # stale cached row with the pre-cancel ``ends_at=None`` /
    # ``status='active'``, defeating the cancel. Mirrors the
    # cache-eviction pattern in ``change_plan`` (services.py:341-351),
    # ``reactivate_subscription`` (services.py:1017-1031), and
    # ``renew_subscription`` (services.py:1130-1139).
    keys_to_evict: list[str] = []
    if subscription.tenant_id:
        keys_to_evict.append(
            f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.tenant_id}"
        )
    if subscription.store_id:
        keys_to_evict.append(
            f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.store_id}"
        )
    if keys_to_evict:
        cache.delete_many(keys_to_evict)

    return subscription


def reactivate_subscription(
    subscription: Subscription,
    *,
    actor=None,
) -> Subscription:
    """
    Reverse a previously-scheduled cancel-at-period-end.

    Clears ``subscription.ends_at`` so the row is no longer in the
    "cancellation scheduled" state. ``status`` is left as ``"active"``
    and the billing clock (``current_period_start`` / ``current_period_end``)
    is **not** modified — the user is billed normally at the existing
    period end as if they had never pressed Cancel.

    Idempotent: a no-op (returns the subscription unchanged, no event
    written) when cancellation is not currently scheduled. This makes
    a double-click on the Reactivate button safe, and means the HTTP
    endpoint can be retried on network blips without polluting the
    audit log with spurious events.

    Args:
        subscription: The subscription to reactivate.
        actor:        The user triggering the reactivation. Recorded in
                      the audit log so we can trace who reversed a cancel.

    Returns:
        The updated ``Subscription`` instance (same object, mutated
        in place when reactivation is actually performed).
    """
    if not subscription.is_cancel_scheduled():
        logger.info(
            "reactivate_subscription: no-op for subscription %s "
            "(status=%s, ends_at=%s)",
            subscription.id,
            subscription.status,
            subscription.ends_at,
        )
        return subscription

    subscription.ends_at = None
    subscription.save(update_fields=["ends_at", "updated_at"])

    record_event(
        subscription,
        EVENT_REACTIVATED,
        actor=actor,
        metadata={"reason": "cancel_reversal"},
    )

    # Evict the cached subscription slot(s) so the next read picks up
    # the cleared ``ends_at``. Mirrors the cache-eviction pattern used
    # in ``change_plan`` (services.py:341-351) and ``renew_subscription``
    # (services.py:815-858).
    keys_to_evict: list[str] = []
    if subscription.tenant_id:
        keys_to_evict.append(
            f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.tenant_id}"
        )
    if subscription.store_id:
        keys_to_evict.append(
            f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.store_id}"
        )
    if keys_to_evict:
        cache.delete_many(keys_to_evict)

    logger.info(
        f"Reactivated subscription {subscription.id} (cancel reversed)"
    )
    return subscription


def renew_subscription(
    subscription: Subscription,
    *,
    new_period_start: datetime = None,
    new_period_end: datetime = None,
    actor=None,
) -> Subscription:
    """
    Renew a subscription that's nearing expiration.

    Args:
        subscription: The subscription to renew
        new_period_start: Start of new billing period
        new_period_end: End of new billing period
        actor: The user renewing the subscription

    Returns:
        The updated Subscription instance
    """
    if subscription.status != STATUS_ACTIVE and subscription.status != STATUS_PAST_DUE:
        raise SubscriptionInactiveError(
            subscription.status, "Only active or past-due subscriptions can be renewed"
        )

    now = timezone.now()
    subscription.status = STATUS_ACTIVE
    subscription.current_period_start = new_period_start or now
    subscription.current_period_end = new_period_end or (now + timedelta(days=30))
    subscription.ends_at = None

    subscription.save(
        update_fields=[
            "status",
            "current_period_start",
            "current_period_end",
            "ends_at",
            "updated_at",
        ]
    )

    record_event(subscription, EVENT_RENEWED, actor=actor)

    logger.info(f"Renewed subscription {subscription.id}")
    return subscription


def upgrade_subscription(
    subscription: Subscription,
    new_plan: SubscriptionPlan,
    *,
    actor=None,
    proration_behavior: str = "create_prorations",
) -> Subscription:
    """
    Upgrade a subscription to a higher-tier plan.

    Updated for tenant-based architecture: upgrades tenant subscription,
    which automatically applies to all stores under the tenant.

    Args:
        subscription: The subscription to upgrade
        new_plan: The new plan to upgrade to
        actor: The user upgrading the subscription
        proration_behavior: How to handle proration

    Returns:
        The updated Subscription instance
    """
    if new_plan.price <= subscription.plan.price:
        raise ValueError("New plan price must be higher for upgrades")

    old_plan = subscription.plan

    # If the subscription is still attached to a single legacy store
    # (no tenant FK), promote it before mutating ``plan``. Otherwise the
    # in-memory ``subscription.plan`` update won't propagate to other
    # stores under the eventual tenant — the user would see the new plan
    # only after they create a new store. We rely on the caller having
    # passed us the sub already promoted in the view layer; this is a
    # belt-and-braces guard. Promotion failure aborts the upgrade — we
    # don't want to apply a new plan to a still-detached row.
    if subscription.tenant_id is None and subscription.store_id is not None:
        promote_subscription_to_tenant(subscription, subscription.store)

    # Upgrade the tenant subscription
    subscription.plan = new_plan
    subscription.save(update_fields=["plan", "updated_at"])

    # Collect every cache key this subscription may have lived under
    # (tenant-keyed and/or the legacy store-keyed) and evict them in
    # one batched call so an in-flight reader can't return a stale
    # model instance cached under the old key.
    keys_to_evict = [
        f"{CACHE_PLAN_PREFIX}{old_plan.slug}",
        f"{CACHE_PLAN_PREFIX}{new_plan.slug}",
    ]
    if subscription.tenant_id:
        keys_to_evict.append(f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.tenant_id}")
    if subscription.store_id:
        keys_to_evict.append(f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.store_id}")
    cache.delete_many(keys_to_evict)

    # Bump RBAC cache versions for every store under the tenant so
    # permission / feature caches rebuild against the new plan on the
    # next read.
    if subscription.tenant_id:
        from apps.permissions.models import StoreMembership
        from apps.permissions.cache import bump_user_version, bump_store_plan_version

        target_store_ids = list(
            subscription.tenant.stores.values_list("id", flat=True)
        )
        target_user_ids = list(
            StoreMembership.objects.filter(
                store_id__in=target_store_ids, is_active=True,
            ).values_list("user_id", flat=True)
        )
        for user_id in target_user_ids:
            bump_user_version(user_id)
        for store_id in target_store_ids:
            bump_store_plan_version(store_id)

    record_event(
        subscription,
        EVENT_UPGRADED,
        actor=actor,
        metadata={
            "old_plan": old_plan.slug,
            "new_plan": new_plan.slug,
            "proration_behavior": proration_behavior,
        },
    )

    # Multi-store tenants in the legacy per-store era may hold other
    # Subscription rows that aren't this one. Promote this sub to its
    # tenant, bind the actor's other stores, and cancel duplicates so
    # the new plan takes effect on the next read for every store.
    propagate_plan_to_all_user_stores(subscription, actor=actor)

    logger.info(f"Upgraded subscription {subscription.id} from {old_plan.slug} to {new_plan.slug}")
    return subscription


def downgrade_subscription(
    subscription: Subscription,
    new_plan: SubscriptionPlan,
    *,
    actor=None,
    effective_at_period_end: bool = True,
) -> Subscription:
    """
    Downgrade a subscription to a lower-tier plan.

    Args:
        subscription: The subscription to downgrade
        new_plan: The new plan to downgrade to
        actor: The user downgrading the subscription
        effective_at_period_end: If True, change takes effect at period end

    Returns:
        The updated Subscription instance
    """
    if new_plan.price >= subscription.plan.price:
        raise ValueError("New plan price must be lower for downgrades")

    old_plan = subscription.plan

    if effective_at_period_end:
        # Schedule downgrade at period end
        subscription.metadata = subscription.metadata or {}
        subscription.metadata["pending_downgrade"] = new_plan.slug
        subscription.save(update_fields=["metadata", "updated_at"])

        record_event(
            subscription,
            EVENT_DOWNGRADED,
            actor=actor,
            metadata={
                "old_plan": old_plan.slug,
                "new_plan": new_plan.slug,
                "effective_at_period_end": True,
            },
        )

        logger.info(
            f"Scheduled downgrade for subscription {subscription.id} from {old_plan.slug} to {new_plan.slug}"
        )
    else:
        # Immediate downgrade
        # ------------------------------------------------------------
        # Refuse the downgrade if the user's current usage exceeds the
        # new plan's caps. We never auto-prune rows — the user is
        # returned a structured error listing exactly which stores and
        # memberships are blocking the change, so they can delete /
        # soft-deactivate them and retry. The scheduled (period-end)
        # branch above is not affected: the user has time to clean up
        # before the change takes effect.
        # ------------------------------------------------------------
        from apps.permissions.services import compute_downgrade_impact
        from apps.permissions.exceptions import DowngradeOverCapacity

        if subscription.tenant_id is not None:
            impact_scope = subscription.tenant
        elif subscription.store_id is not None:
            impact_scope = subscription.store
        else:
            impact_scope = None

        if impact_scope is not None:
            impact = compute_downgrade_impact(impact_scope, new_plan)
            if impact["stores"] or impact["users"]:
                raise DowngradeOverCapacity(
                    stores=impact["stores"],
                    users=impact["users"],
                    limits=impact["limits"],
                    new_plan_slug=new_plan.slug,
                )

        subscription.plan = new_plan
        subscription.save(update_fields=["plan", "updated_at"])

        record_event(
            subscription,
            EVENT_DOWNGRADED,
            actor=actor,
            metadata={
                "old_plan": old_plan.slug,
                "new_plan": new_plan.slug,
                "effective_at_period_end": False,
            },
        )

        # Evict plan + subscription cache slots in a single batched call.
        # Includes the legacy store-keyed slot when the sub is still
        # store-only, and the tenant-keyed slot when it's been promoted.
        keys_to_evict = [
            f"{CACHE_PLAN_PREFIX}{old_plan.slug}",
            f"{CACHE_PLAN_PREFIX}{new_plan.slug}",
        ]
        if subscription.tenant_id:
            keys_to_evict.append(
                f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.tenant_id}"
            )
        if subscription.store_id:
            keys_to_evict.append(
                f"{CACHE_SUBSCRIPTION_PREFIX}{subscription.store_id}"
            )
        cache.delete_many(keys_to_evict)

        # Bump RBAC cache versions for every store and active member.
        from apps.permissions.models import StoreMembership
        from apps.permissions.cache import bump_user_version, bump_store_plan_version

        if subscription.tenant_id:
            target_store_ids = list(
                subscription.tenant.stores.values_list("id", flat=True)
            )
        else:
            target_store_ids = [subscription.store_id]

        target_user_ids = list(
            StoreMembership.objects.filter(
                store_id__in=target_store_ids, is_active=True,
            ).values_list("user_id", flat=True)
        )
        for user_id in target_user_ids:
            bump_user_version(user_id)
        for store_id in target_store_ids:
            bump_store_plan_version(store_id)

        # Mirror the upgrade path: apply the new plan to every other
        # store the actor owns so a single downgrade doesn't leave one
        # store on the old plan.
        propagate_plan_to_all_user_stores(subscription, actor=actor)

        logger.info(
            f"Downgraded subscription {subscription.id} from {old_plan.slug} to {new_plan.slug}"
        )

    return subscription


def get_active_subscription(store: Store) -> Optional[Subscription]:
    """
    Get the active subscription for a store's tenant with caching.

    Now uses tenant-based subscription architecture. Each tenant has one subscription
    that applies to all stores under that tenant.

    Falls back to store-based subscription for migration period.

    Args:
        store: The store to get subscription for (via its tenant)

    Returns:
        The active Subscription instance or None
    """
    # Try tenant-based subscription first (new architecture)
    if store.tenant:
        cache_key = f"{CACHE_SUBSCRIPTION_PREFIX}{store.tenant.id}"
        subscription = cache.get(cache_key)

        if subscription is None:
            try:
                subscription = store.tenant.subscription
                if subscription and not subscription.is_active():
                    subscription = None
            except Subscription.DoesNotExist:
                subscription = None

            if subscription:
                cache.set(cache_key, subscription, CACHE_KEY_TIMEOUT)

        if subscription:
            return subscription

    # Fallback to store-based subscription (migration period)
    cache_key = f"{CACHE_SUBSCRIPTION_PREFIX}{store.id}"
    subscription = cache.get(cache_key)

    if subscription is None:
        try:
            subscription = store.subscription
            if subscription and not subscription.is_active():
                subscription = None
        except Subscription.DoesNotExist:
            subscription = None

        if subscription:
            cache.set(cache_key, subscription, CACHE_KEY_TIMEOUT)

    return subscription


def check_plan_limits(store: Store) -> Dict[str, Any]:
    """
    Check current usage against subscription plan limits.

    Updated to support both tenant-based (new) and store-based (legacy) subscriptions
    for smooth migration period.

    Args:
        store: The store to check limits for

    Returns:
        Dict with limit information and usage
    """
    subscription = get_active_subscription(store)

    if not subscription:
        return {
            "has_active_subscription": False,
            "limits": {},
            "usage": {},
            "exceeded": {},
        }

    plan = subscription.plan

    # Count usage based on subscription type
    if subscription.tenant:
        # Tenant-based: count across all tenant stores
        stores_count = Store.objects.filter(
            tenant=subscription.tenant,
            is_deleted=False,
        ).count()

        # Count users across all tenant stores, excluding store owners
        try:
            from apps.permissions.models import Role

            owner_role = Role.objects.filter(slug="store-owner", store__isnull=True).first()
            if owner_role:
                # Get all owner memberships across all tenant stores
                owner_memberships = StoreMembership.objects.filter(
                    store__tenant=subscription.tenant, role=owner_role, is_active=True
                )
                owner_ids = list(owner_memberships.values_list("user_id", flat=True))
            else:
                owner_ids = []
                logger.warning(f"Tenant {subscription.tenant.id}: No 'store-owner' role found")
        except Exception as e:
            logger.warning(f"Failed to look up store owners: {str(e)}")
            owner_ids = []

        # ``reserved_users`` is the value write-paths (add_member,
        # reactivate_member, invite_member) MUST enforce against. A
        # deactivated row still occupies its seat; only hard-delete
        # frees it. Without this count the deactivate/reactivate
        # bypass reopens under tenant-based subscriptions.
        # ``users`` is the active-only count, kept for UI display.
        counts = (
            StoreMembership.objects.filter(store__tenant=subscription.tenant)
            .exclude(user_id__in=owner_ids)
            .aggregate(
                users=Count("id", filter=Q(is_active=True)),
                reserved_users=Count("id"),
            )
        )
        users_count = counts["users"]
        reserved_users_count = counts["reserved_users"]
        logger.info(
            f"Tenant {subscription.tenant.id} usage: {stores_count} stores, "
            f"{users_count} active / {reserved_users_count} reserved users "
            f"(excluding {len(owner_ids)} owners)"
        )
    else:
        # Store-based: count for this store only
        stores_count = 1  # Just this store

        # Count users excluding store owners
        try:
            from apps.permissions.models import Role

            owner_role = Role.objects.filter(slug="store-owner", store__isnull=True).first()
            if owner_role:
                owner_memberships = StoreMembership.objects.filter(
                    store=store, role=owner_role, is_active=True
                )
                owner_ids = list(owner_memberships.values_list("user_id", flat=True))
            else:
                owner_ids = []
                logger.warning(f"Store {store.id}: No 'store-owner' role found")
        except Exception as e:
            logger.warning(f"Failed to look up store owners: {str(e)}")
            owner_ids = []

        # ``reserved_users`` is the value write-paths MUST enforce
        # against. A deactivated row still occupies its seat; only
        # hard-delete frees it. ``users`` (active-only) is kept for
        # the UI's "X / Y active" display.
        counts = (
            StoreMembership.objects.filter(store=store)
            .exclude(user_id__in=owner_ids)
            .aggregate(
                users=Count("id", filter=Q(is_active=True)),
                reserved_users=Count("id"),
            )
        )
        users_count = counts["users"]
        reserved_users_count = counts["reserved_users"]
        logger.info(
            f"Store {store.id} usage: {stores_count} stores, {users_count} active / "
            f"{reserved_users_count} reserved users (excluding {len(owner_ids)} owners)"
        )

    limits = {
        "max_stores": plan.max_stores,
        "max_users": plan.max_users,
        "max_products": plan.max_products,
        "max_orders_per_month": plan.max_orders_per_month,
        "max_warehouses": plan.max_warehouses,
    }

    usage = {
        "stores": stores_count,
        "users": users_count,
        # Reserved = active + inactive. A deactivated membership row still
        # occupies its seat; only hard-delete frees it. This is the value
        # write-paths (add_member, reactivate_member, invite_member) must
        # enforce against to prevent the deactivate/reactivate bypass.
        "reserved_users": reserved_users_count,
        # Add more usage metrics as needed
        "products": 0,  # Implement when products module is ready
        "orders_this_month": 0,  # Implement when orders module is ready
        "warehouses": 0,  # Implement when warehouses module is ready
    }

    exceeded = {}
    for limit_type, limit_value in limits.items():
        usage_key = limit_type.replace("max_", "")
        current_value = usage.get(usage_key, 0)
        if current_value >= limit_value:
            exceeded[limit_type] = {
                "limit": limit_value,
                "current": current_value,
                "exceeded_by": current_value - limit_value,
            }

    return {
        "has_active_subscription": True,
        "plan": {
            "id": plan.id,
            "name": plan.name,
            "slug": plan.slug,
            "price": str(plan.price),
            "currency": plan.currency,
        },
        "limits": limits,
        "usage": usage,
        "exceeded": exceeded,
        "status": subscription.status,
        "is_active": subscription.is_active(),
    }


def enforce_plan_limit(store: Store, limit_type: str, current_value: int) -> None:
    """
    Enforce a plan limit for a store.

    Args:
        store: The store to enforce limit for
        limit_type: Type of limit (e.g., 'max_stores', 'max_users')
        current_value: Current usage value (BEFORE adding the new item)

    Raises:
        PlanLimitExceeded: If limit would be exceeded

    Note:
        This function checks if adding ONE MORE item would exceed the limit.
        For example, if current_value is 4 and limit is 5, this allows the operation.
        If current_value is 5 and limit is 5, this raises an exception.
    """
    subscription = get_active_subscription(store)

    if not subscription:
        raise PlanLimitExceeded(limit_type, current_value + 1, 0)

    plan = subscription.plan
    limit_value = getattr(plan, limit_type, None)

    if limit_value is None:
        logger.warning(f"Plan limit {limit_type} not found for plan {plan.slug}")
        return

    # Check if adding ONE MORE item would exceed the limit
    if current_value >= limit_value:
        raise PlanLimitExceeded(limit_type, current_value + 1, limit_value)


def enforce_reserved_seat_cap(
    store: Store,
    *,
    action: str,
    block_when_equal: bool = True,
) -> None:
    """Raise ``PlanLimitExceeded`` if the plan's seat cap is at/over limit.

    Centralizes the seat-cap enforcement that previously lived as
    copy-pasted logic in ``add_member``, ``reactivate_member``, and the
    ``invite_member`` / ``activate_member`` views. Using this helper on
    every write path is what closes the deactivate/reactivate bypass.

    Args:
        store: The store the membership belongs to.
        action: Human label for the operation (e.g. "add", "reactivate").
            Used in the exception message so the user sees a clear
            description of what was blocked.
        block_when_equal: If True, block when ``reserved_users >= max``
            (default — write paths that *add* a row use this). If False,
            block only when ``reserved_users > max`` — used by paths
            that *flip an existing row* (e.g. reactivation), where the
            row being modified is already counted in ``reserved_users``
            so equality is not a bypass.

    Raises:
        PlanLimitExceeded: If the cap is at or beyond the limit.
    """
    limits_info = check_plan_limits(store)
    reserved_users = limits_info["usage"].get("reserved_users")
    if reserved_users is None:
        # ``reserved_users`` is always present in current deployments.
        # If it's absent we cannot enforce; log and let the request
        # through rather than block on stale code.
        logger.warning(
            "check_plan_limits returned no reserved_users for store %s; "
            "skipping seat-cap enforcement",
            getattr(store, "id", None),
        )
        return

    max_users = limits_info.get("limits", {}).get("max_users", 0) or 0
    if not max_users:
        return  # No plan / unlimited — nothing to enforce.

    over_cap = (
        reserved_users > max_users
        if not block_when_equal
        else reserved_users >= max_users
    )
    if not over_cap:
        return

    if action == "reactivate":
        message = (
            f"Cannot reactivate this member. Your plan allows "
            f"{max_users} team members but {reserved_users} are "
            f"currently reserved across your stores (including "
            f"deactivated members). Remove a member or upgrade "
            f"your plan to free up a seat."
        )
        # Reactivation doesn't change the reserved count, so the
        # current "usage" we report equals ``reserved_users`` — no
        # ``+1`` adjustment.
        raise PlanLimitExceeded(
            "max_users", reserved_users, max_users, message=message,
        )

    # Default ``add`` message — ``current_value`` is reported as the
    # count AFTER the write so the UI can render the right CTA.
    raise PlanLimitExceeded(
        "max_users", reserved_users + 1, max_users,
    )


def check_trial_expiry(subscription: Subscription) -> bool:
    """
    Check if a trial subscription has expired and handle accordingly.

    Args:
        subscription: The trial subscription to check

    Returns:
        True if trial expired, False otherwise

    Raises:
        TrialExpiredError: If trial has expired
    """
    if subscription.status != STATUS_TRIALING:
        return False

    if subscription.trial_ends_at and subscription.trial_ends_at < timezone.now():
        transition_status(subscription, STATUS_EXPIRED, reason="trial_expired")
        raise TrialExpiredError(subscription.trial_ends_at)

    return False
