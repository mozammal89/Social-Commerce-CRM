"""
Tests for plan cancellation flow.

Covers:
* ``Subscription.is_cancel_scheduled`` (apps.permissions.models) — the
  single source of truth for "cancellation is pending at period end".
* ``Subscription.is_canceled_or_canceling`` (apps.permissions.models) —
  broader predicate used by the manage-page banner so the user gets
  visible feedback on every cancel branch (scheduled + immediate).
* ``cancel_subscription`` (apps.subscriptions.services) — scheduled
  cancel sets ``ends_at`` to ``current_period_end``, leaves status as
  ``active``, and records an ``EVENT_CANCELED`` event.
* ``reactivate_subscription`` (apps.subscriptions.services) — clears
  ``ends_at``, records ``EVENT_REACTIVATED``, evicts the cache, and is
  a safe no-op when cancellation isn't scheduled.
* ``resolve_user_subscription`` (apps.subscriptions.services) —
  returns a sub even when cancellation is scheduled, so the sidebar
  Store Management section + dashboard don't disappear on cancel.
* The ``manage_subscription`` view (apps.subscriptions.views) —
  exposes ``cancellation_scheduled`` in the context so the template
  can render the banner + Reactivate card.
* The ``dashboard_home`` view (apps.dashboard.views) — when the user
  has stores but no live subscription, renders the dashboard with a
  ``subscription_needs_attention`` banner instead of force-redirecting
  them to the manage page (the old behaviour produced a confusing
  redirect loop combined with the missing Store Management sidebar).
"""

from __future__ import annotations

import pytest
from django.utils import timezone

from apps.subscriptions.services import cancel_subscription, reactivate_subscription


# ---------------------------------------------------------------------------
# Subscription.is_cancel_scheduled — model-level predicate
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestIsCancelScheduled:
    def test_active_with_future_ends_at_is_scheduled(
        self, tenant_with_growth_sub,
    ):
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        sub.ends_at = timezone.now() + timezone.timedelta(days=10)
        sub.save()
        assert sub.is_cancel_scheduled() is True

    def test_active_without_ends_at_is_not_scheduled(
        self, tenant_with_growth_sub,
    ):
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        assert sub.ends_at is None
        assert sub.is_cancel_scheduled() is False

    def test_active_with_past_ends_at_is_not_scheduled(
        self, tenant_with_growth_sub,
    ):
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        sub.ends_at = timezone.now() - timezone.timedelta(days=1)
        sub.save()
        assert sub.is_cancel_scheduled() is False

    def test_trialing_with_ends_at_is_not_scheduled(
        self, tenant_with_growth_sub,
    ):
        """Trial cancel goes through ``transition_status`` (immediate)
        and never sets ``ends_at``. A trialing row with a stray
        ``ends_at`` shouldn't show as scheduled — the predicate is
        scoped to ``status='active'``."""
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        sub.status = "trialing"
        sub.ends_at = timezone.now() + timezone.timedelta(days=10)
        sub.save()
        assert sub.is_cancel_scheduled() is False


@pytest.mark.django_db
class TestIsCanceledOrCanceling:
    """Broader predicate used by the manage-page banner — captures
    *every* cancel state so the user gets visible feedback regardless
    of which cancel branch the service took."""

    def test_active_with_future_ends_at(self, tenant_with_growth_sub):
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        sub.ends_at = timezone.now() + timezone.timedelta(days=10)
        sub.save()
        assert sub.is_canceled_or_canceling() is True

    def test_canceled_status_is_canceled_or_canceling(
        self, tenant_with_growth_sub,
    ):
        """A sub whose ``status='canceled'`` is also 'canceled or
        canceling' — even with ``ends_at=None`` (which is the
        immediate-cancel branch)."""
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        sub.status = "canceled"
        sub.ends_at = None
        sub.save()
        assert sub.is_canceled_or_canceling() is True

    def test_active_no_ends_at_is_neither(
        self, tenant_with_growth_sub,
    ):
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        assert sub.is_canceled_or_canceling() is False

    def test_trialing_with_ends_at_is_neither(
        self, tenant_with_growth_sub,
    ):
        """The broad predicate is also gated on actual cancel state —
        a stray trialing row with ends_at shouldn't show."""
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        sub.status = "trialing"
        sub.ends_at = timezone.now() + timezone.timedelta(days=10)
        sub.save()
        assert sub.is_canceled_or_canceling() is False


# ---------------------------------------------------------------------------
# cancel_subscription — service layer
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestCancelSubscription:
    def test_scheduled_sets_ends_at_and_records_event(
        self, tenant_with_growth_sub, user,
    ):
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        old_period_end = sub.current_period_end

        result = cancel_subscription(
            sub,
            cancel_at_period_end=True,
            actor=user,
            reason="too expensive",
        )
        result.refresh_from_db()

        # Status stays active — user keeps access until period end.
        assert result.status == "active"
        # ends_at == current_period_end (the marker that
        # is_cancel_scheduled looks for).
        assert result.ends_at == old_period_end

        events = list(result.events.all())
        assert len(events) == 1
        assert events[0].event_type == "subscription.canceled"
        assert events[0].metadata.get("cancel_at_period_end") is True
        assert events[0].metadata.get("reason") == "too expensive"

    def test_scheduled_makes_is_cancel_scheduled_true(
        self, tenant_with_growth_sub, user,
    ):
        sub = tenant_with_growth_sub
        cancel_subscription(
            sub, cancel_at_period_end=True, actor=user,
        )
        sub.refresh_from_db()
        assert sub.is_cancel_scheduled() is True

    def test_scheduled_evicts_subscription_cache(
        self, tenant_with_growth_sub, user,
    ):
        """``cancel_subscription`` must evict the per-tenant and per-store
        subscription cache keys so the next ``get_active_subscription``
        call picks up the freshly-set ``ends_at``. Without this,
        downstream views (dashboard's plan display, team-management
        ``/filter``, ``plan_limit`` lookups) would keep reading the
        pre-cancel row with ``ends_at=None`` — silently undoing the
        cancel for any caller that reads through the cache.

        Regression test for the user-reported "Cancel Subscription
        toast shows but page state doesn't change" symptom: the cancel
        API succeeded, but the cache was poisoned with the stale row.
        """
        from django.core.cache import cache

        from apps.subscriptions.services import (
            CACHE_SUBSCRIPTION_PREFIX,
            get_active_subscription,
        )

        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        tenant = sub.tenant
        # The fixture only sets ``tenant``; legacy store-based rows
        # use ``subscription.store_id`` — set both paths.
        store_id = sub.store_id

        # Prime both cache slots with the pre-cancel row.
        if tenant:
            cache.set(
                f"{CACHE_SUBSCRIPTION_PREFIX}{tenant.id}",
                sub,
                60,
            )
        if store_id:
            cache.set(
                f"{CACHE_SUBSCRIPTION_PREFIX}{store_id}",
                sub,
                60,
            )

        cancel_subscription(sub, cancel_at_period_end=True, actor=user)
        sub.refresh_from_db()

        # Both cache slots must be evicted.
        if tenant:
            assert (
                cache.get(f"{CACHE_SUBSCRIPTION_PREFIX}{tenant.id}") is None
            ), "Tenant subscription cache should be evicted on cancel"
        if store_id:
            assert (
                cache.get(f"{CACHE_SUBSCRIPTION_PREFIX}{store_id}") is None
            ), "Store subscription cache should be evicted on cancel"

        # And ``get_active_subscription`` (the function most views use)
        # must now read the freshly-canceled row.
        if store_id:
            from apps.stores.models import Store
            store = Store.objects.get(id=store_id)
            fresh = get_active_subscription(store)
            assert fresh is not None
            assert fresh.ends_at == sub.ends_at, (
                "get_active_subscription returned a stale row "
                f"(cached ends_at={fresh.ends_at!r}, DB ends_at={sub.ends_at!r})"
            )

    def test_immediate_cancel_also_evicts_cache(
        self, tenant_with_growth_sub, user,
    ):
        """``cancel_at_period_end=False`` also flips status to
        ``canceled`` — same cache-eviction requirement applies so
        downstream callers see the terminal state."""
        from django.core.cache import cache

        from apps.subscriptions.services import (
            CACHE_SUBSCRIPTION_PREFIX,
        )

        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        tenant = sub.tenant

        if tenant:
            cache.set(
                f"{CACHE_SUBSCRIPTION_PREFIX}{tenant.id}",
                sub,
                60,
            )

        cancel_subscription(
            sub, cancel_at_period_end=False, actor=user,
        )
        sub.refresh_from_db()
        assert sub.status == "canceled"

        if tenant:
            assert (
                cache.get(f"{CACHE_SUBSCRIPTION_PREFIX}{tenant.id}") is None
            ), (
                "Tenant subscription cache should be evicted on immediate "
                "cancel too"
            )

    def test_scheduled_when_current_period_end_is_none(
        self, tenant_with_growth_sub, user,
    ):
        """Regression test for the user-reported bug: cancel returns
        ``{"ends_at": null}`` when the row has no ``current_period_end``
        set, leaving ``is_cancel_scheduled()`` False and the
        Cancellation banner + Reactivate button invisible. The service
        must fall back to a sensible default period end so the cancel
        is actually visible.

        Bug repro path:
          1. User has an active sub with ``current_period_end=None``
             (legacy / imported / pre-migration data).
          2. User clicks Cancel Subscription.
          3. ``cancel_subscription`` sets ``ends_at = current_period_end``
             which is None.
          4. API returns 200 ``{ends_at: null}``.
          5. Toast shows "Subscription cancelled successfully".
          6. Reload: ``is_cancel_scheduled()`` is False, banner
             doesn't render, Cancel button stays visible.

        Fix: when ``current_period_end`` is None, fall back to
        ``current_period_start + 30d`` (or ``starts_at + 30d``, or
        ``now + 30d``) — whichever anchor produces a meaningful future
        date.
        """
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        # Simulate the legacy / pre-migration data the user has.
        sub.current_period_end = None
        sub.current_period_start = None
        sub.starts_at = timezone.now() - timezone.timedelta(days=5)
        sub.save()

        cancel_subscription(sub, cancel_at_period_end=True, actor=user)
        sub.refresh_from_db()

        # The cancel must actually mark the sub as canceling.
        assert sub.ends_at is not None, (
            "cancel_subscription left ends_at=None when current_period_end "
            "was None — the cancel is invisible to is_cancel_scheduled() "
            "and the banner won't render. API returned 200 but no UI "
            "feedback."
        )
        assert sub.is_cancel_scheduled() is True, (
            "Even after cancel_subscription, is_cancel_scheduled() is "
            "False because ends_at is None — manage page shows no "
            "banner and the user sees no state change after reload."
        )
        # The fallback should produce a future date so the banner
        # shows a meaningful "ends on YYYY-MM-DD" message.
        assert sub.ends_at > timezone.now(), (
            f"Fallback ends_at {sub.ends_at!r} should be in the future "
            f"(now={timezone.now()!r})."
        )

    def test_scheduled_when_current_period_end_is_in_the_past(
        self, tenant_with_growth_sub, user,
    ):
        """If ``current_period_end`` is in the past (sub lapsed but
        still marked ``status='active'`` because renewal hasn't
        run), ``is_cancel_scheduled`` correctly returns False — the
        period already elapsed, the user no longer has access. The
        immediate-cancel path (``transition_status``) is the right
        one in this state, not the period-end fallback.
        """
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        sub.current_period_end = timezone.now() - timezone.timedelta(days=1)
        sub.save()

        cancel_subscription(sub, cancel_at_period_end=True, actor=user)
        sub.refresh_from_db()

        # The past ``current_period_end`` propagates to ``ends_at``
        # directly — the user is past their period, so a scheduled
        # cancel at the past date doesn't make sense.
        assert sub.ends_at is not None
        assert sub.ends_at == sub.current_period_end


# ---------------------------------------------------------------------------
# reactivate_subscription — service layer
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestReactivateSubscription:
    def test_clears_ends_at_and_records_reactivated_event(
        self, tenant_with_growth_sub, user,
    ):
        sub = tenant_with_growth_sub
        cancel_subscription(
            sub, cancel_at_period_end=True, actor=user,
        )
        sub.refresh_from_db()
        assert sub.is_cancel_scheduled() is True

        reactivate_subscription(sub, actor=user)
        sub.refresh_from_db()

        assert sub.ends_at is None
        assert sub.is_cancel_scheduled() is False
        # Status unchanged — was active, still active.
        assert sub.status == "active"

        events = list(sub.events.order_by("occurred_at"))
        assert [e.event_type for e in events] == [
            "subscription.canceled",
            "subscription.reactivated",
        ]
        assert events[-1].metadata.get("reason") == "cancel_reversal"

    def test_idempotent_when_not_cancelled(
        self, tenant_with_growth_sub, user,
    ):
        """Calling reactivate on a sub that isn't cancelled is a no-op:
        no state change, no event written. This makes double-click on
        the Reactivate button safe and lets the HTTP endpoint be
        retried on network blips."""
        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        assert sub.is_cancel_scheduled() is False
        event_count_before = sub.events.count()

        result = reactivate_subscription(sub, actor=user)
        result.refresh_from_db()

        assert result.ends_at is None
        assert result.events.count() == event_count_before


# ---------------------------------------------------------------------------
# manage_subscription view — context exposes cancellation_scheduled
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestManageSubscriptionContext:
    def test_cancellation_scheduled_flag_set_when_pending(
        self, tenant_with_growth_sub, user,
    ):
        """When a cancel-at-period-end is on the sub, the manage view
        renders the cancellation banner + Reactivate card and hides
        the Cancel card. End-to-end via the test client."""
        from django.test import Client

        sub = tenant_with_growth_sub
        cancel_subscription(
            sub, cancel_at_period_end=True, actor=user,
        )

        c = Client()
        c.force_login(user)
        r = c.get('/subscriptions/manage/')

        assert r.status_code == 200
        # Banner present.
        assert b'Cancellation scheduled' in r.content
        # Reactivate sidebar card present (both the banner button and
        # the sidebar button trigger ``reactivateSubscription()``).
        assert b'reactivateSubscription()' in r.content
        # Cancel card hidden — the user can't press Cancel twice.
        assert b'<i class="bi bi-x-lg"></i> Cancel Subscription' not in r.content

    def test_no_banner_when_not_scheduled(
        self, tenant_with_growth_sub, user,
    ):
        """Default state — no banner, Reactivate sidebar card hidden,
        normal Cancel card visible. The ``reactivateSubscription``
        JS function may still be defined in the script block (its
        handler is gated by ``can_cancel or cancellation_scheduled``);
        what we care about here is the *visible* Reactivate card."""
        from django.test import Client

        c = Client()
        c.force_login(user)
        r = c.get('/subscriptions/manage/')

        assert r.status_code == 200
        assert b'Cancellation scheduled' not in r.content
        # The Reactivate *sidebar card* has this exact onclick pattern;
        # the JS function comment block also mentions the same words
        # in prose, so we check the button attribute specifically.
        assert b'onclick="reactivateSubscription()" class="btn-cancel-sub"' not in r.content
        # The Cancel card is the default state.
        assert b'onclick="confirmCancel()" class="btn-cancel-sub"' in r.content

    def test_banner_shows_for_immediate_cancel(
        self, tenant_with_growth_sub, user,
    ):
        """When the cancel branch took the immediate path
        (``status='canceled'`` with no ``ends_at``), the banner still
        appears so the user sees feedback — but the Reactivate button
        is replaced with a 'resubscribe' link, since reversing a
        fully-canceled sub needs a re-subscribe flow rather than the
        ends_at-clearing one."""
        from django.test import Client
        from apps.subscriptions.services import cancel_subscription

        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        # Force the immediate-cancel branch by passing
        # cancel_at_period_end=False.
        cancel_subscription(
            sub, cancel_at_period_end=False, actor=user,
        )
        sub.refresh_from_db()
        assert sub.status == "canceled"

        c = Client()
        c.force_login(user)
        r = c.get('/subscriptions/manage/')

        assert r.status_code == 200
        # Banner still visible (broader predicate).
        assert b'Cancellation scheduled' in r.content
        # But no Reactivate *button* — resubscribe CTA only.
        assert b'onclick="reactivateSubscription()"' not in r.content
        # Plans-page link instead. ``?upgrade=1`` so the plans view
        # doesn't bounce the user back here (since they have stores,
        # the plans view redirects to manage unless explicitly in
        # upgrade mode).
        assert b'href="/subscriptions/plans/?upgrade=1"' in r.content

# ---------------------------------------------------------------------------
# resolve_user_subscription — must NOT return None for scheduled-cancel subs
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestResolveUserSubscription:
    """After cancelling at period end, the user keeps access until the
    period ends — so the resolver must keep returning the sub, otherwise
    the sidebar Store Management section disappears and the dashboard
    redirects to /subscriptions/manage/ with a 'subscription no longer
    active' flash."""

    def test_scheduled_cancel_still_resolves(
        self, tenant_with_growth_sub, user,
    ):
        from apps.subscriptions.services import resolve_user_subscription

        sub = tenant_with_growth_sub
        cancel_subscription(
            sub, cancel_at_period_end=True, actor=user,
        )
        sub.refresh_from_db()
        # Row is still active + has a future ends_at — that's the
        # marker the resolver needs to keep returning it.
        assert sub.status == "active"
        assert sub.is_cancel_scheduled() is True

        resolved = resolve_user_subscription(user)
        assert resolved is not None
        assert resolved.id == sub.id

    def test_immediate_cancel_returns_none(
        self, tenant_with_growth_sub, user,
    ):
        """A truly canceled sub (status='canceled', no ends_at) has
        no active access — the resolver should return None so the
        dashboard correctly redirects the user to re-subscribe."""
        from apps.subscriptions.services import resolve_user_subscription

        sub = tenant_with_growth_sub
        # Force the immediate-cancel branch.
        cancel_subscription(
            sub, cancel_at_period_end=False, actor=user,
        )
        sub.refresh_from_db()
        assert sub.status == "canceled"

        resolved = resolve_user_subscription(user)
        assert resolved is None

    def test_active_no_cancel_resolves(
        self, tenant_with_growth_sub, user,
    ):
        """Sanity check — the unmodified active sub still resolves."""
        from apps.subscriptions.services import resolve_user_subscription

        sub = tenant_with_growth_sub
        sub.refresh_from_db()
        assert sub.is_cancel_scheduled() is False

        resolved = resolve_user_subscription(user)
        assert resolved is not None
        assert resolved.id == sub.id


# ---------------------------------------------------------------------------
# change_plan — reactivate after terminal state (canceled/expired)
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestChangePlanReactivatesTerminalStatus:
    """When a user with ``status='canceled'`` (immediate cancel) or
    ``status='expired'`` (lapsed trial) picks a new plan, ``change_plan``
    must flip them back to ``active`` before dispatch. Otherwise the
    row keeps its terminal status, ``is_active()`` keeps returning False,
    and every gated write path (invite members, create roles, override
    permissions) keeps 403-ing the user even though they just paid.

    Reactivating the row in ``change_plan`` is a one-stop fix that
    applies whether the user came in through the checkout flow
    (``subscription_checkout`` POST -> ``change_plan``) or the in-place
    API (``POST /subscriptions/api/update-plan/`` -> ``change_plan``).
    """

    def test_canceled_sub_picks_new_plan_becomes_active(
        self, tenant_with_growth_sub, user,
    ):
        from apps.subscriptions.services import (
            cancel_subscription,
            change_plan,
        )
        from apps.permissions.models import SubscriptionPlan

        sub = tenant_with_growth_sub
        # Immediate cancel -> status='canceled', ends_at=None.
        cancel_subscription(sub, cancel_at_period_end=False, actor=user)
        sub.refresh_from_db()
        assert sub.status == "canceled"
        assert sub.ends_at is None

        # Pick a higher-priced plan. (We need a separate plan row with a
        # higher ``price`` so ``change_plan`` dispatches to the upgrade
        # branch. The Growth fixture plan is $49.)
        higher = SubscriptionPlan.objects.create(
            name="Test Pro", slug="test-pro", price=149,
            max_users=20, max_stores=3, max_products=10000,
        )

        result = change_plan(
            sub, higher, actor=user, effective_immediately=True,
        )
        result.refresh_from_db()

        # Status flipped to active; the user is no longer canceled.
        assert result.status == "active"
        # ends_at stayed clear (no scheduled-cancel ghost).
        assert result.ends_at is None
        # Plan was actually applied.
        assert result.plan_id == higher.id
        # Audit trail: an EVENT_REACTIVATED event was recorded.
        events = list(result.events.order_by("occurred_at"))
        reactivated = [
            e for e in events
            if e.event_type == "subscription.reactivated"
        ]
        assert reactivated, (
            "Expected an EVENT_REACTIVATED event after plan change on a "
            "canceled subscription."
        )
        assert reactivated[-1].metadata.get("previous_status") == "canceled"

    def test_canceled_sub_picks_lower_plan_becomes_active(
        self, tenant_with_growth_sub, user,
    ):
        """The downgrade branch must also flip status — same fix as
        upgrade, just the dispatch path differs."""
        from apps.subscriptions.services import (
            cancel_subscription,
            change_plan,
        )
        from apps.permissions.models import SubscriptionPlan

        sub = tenant_with_growth_sub
        cancel_subscription(sub, cancel_at_period_end=False, actor=user)
        sub.refresh_from_db()
        assert sub.status == "canceled"

        lower = SubscriptionPlan.objects.create(
            name="Test Starter", slug="test-starter", price=19,
            max_users=3, max_stores=1, max_products=500,
        )

        result = change_plan(
            sub, lower, actor=user, effective_immediately=True,
        )
        result.refresh_from_db()
        assert result.status == "active"
        assert result.plan_id == lower.id

    def test_scheduled_cancel_picks_new_plan_also_reactivates(
        self, tenant_with_growth_sub, user,
    ):
        """A sub with ``status='active' + ends_at=future`` (scheduled
        cancel) must also be reactivated in full — the new fix clears
        ``ends_at`` along with flipping status so the user doesn't carry
        the scheduled-cancel ghost into the new billing period."""
        from apps.subscriptions.services import (
            cancel_subscription,
            change_plan,
        )
        from apps.permissions.models import SubscriptionPlan
        from django.utils import timezone

        sub = tenant_with_growth_sub
        cancel_subscription(sub, cancel_at_period_end=True, actor=user)
        sub.refresh_from_db()
        assert sub.status == "active"
        assert sub.ends_at is not None
        assert sub.ends_at > timezone.now()

        higher = SubscriptionPlan.objects.create(
            name="Test Pro", slug="test-pro", price=149,
            max_users=20, max_stores=3, max_products=10000,
        )
        result = change_plan(
            sub, higher, actor=user, effective_immediately=True,
        )
        result.refresh_from_db()

        # Status stays active (already was), but ends_at is now wiped.
        assert result.status == "active"
        assert result.ends_at is None
        assert result.plan_id == higher.id


# ---------------------------------------------------------------------------
# dashboard_home — subscription-needs-attention banner vs hard redirect
# ---------------------------------------------------------------------------
@pytest.mark.django_db
class TestDashboardSubscriptionNeedsAttention:
    """When the user has stores but their subscription is canceled/expired
    /past_due (i.e. immediate cancel), the dashboard used to hard-redirect
    them to /subscriptions/manage/ — combined with the missing Store
    Management sidebar entry, this produced a confusing loop. The fix
    keeps the user on the dashboard with a clear ``subscription_needs_
    attention`` banner pointing them to plans/manage instead.
    """

    def _ensure_user_membership(self, user, tenant):
        """The dashboard's "has stores" check queries StoreMembership
        directly — the same table the sidebar uses to list stores. The
        ``tenant`` fixture creates a Store row but no membership; in
        production the store-creation flow attaches the user as
        ``store-owner`` via ``add_member``. Mimic that here so the
        dashboard sees the user as "has stores" and the role's
        ``"*"`` wildcard grant resolves to a real
        ``dashboard.view`` permission."""
        from apps.permissions.models import Role, StoreMembership
        from apps.permissions.seeders.roles_seeder import RolesSeeder
        from apps.permissions.seeders.permissions_seeder import (
            RolePermissionsSeeder,
        )
        from apps.stores.models import Store

        RolesSeeder().run()
        RolePermissionsSeeder().run()
        owner_role = Role.objects.get(slug="store-owner", store__isnull=True)
        store = Store.objects.filter(tenant=tenant).first()
        StoreMembership.objects.create(
            user=user, store=store, role=owner_role, is_active=True,
        )

    def test_dashboard_renders_with_banner_when_canceled(
        self, tenant_with_growth_sub, user,
    ):
        from django.test import Client
        from apps.subscriptions.services import cancel_subscription

        sub = tenant_with_growth_sub
        cancel_subscription(sub, cancel_at_period_end=False, actor=user)
        sub.refresh_from_db()
        assert sub.status == "canceled"
        self._ensure_user_membership(user, sub.tenant)

        c = Client()
        c.force_login(user)
        r = c.get("/dashboard/")

        # Dashboard is rendered (200, no redirect to manage).
        assert r.status_code == 200, (
            f"Expected 200 but got {r.status_code}. "
            f"Headers: {dict(r.headers)}"
        )
        # The banner explains the situation and offers a re-subscribe CTA.
        assert b"Your subscription is no longer active" in r.content
        # Re-subscribe CTA links to plans with ?upgrade=1.
        assert b'href="/subscriptions/plans/?upgrade=1"' in r.content
        # Direct "Manage subscription" link is also available.
        assert b'href="/subscriptions/manage/"' in r.content
        # And the Store Management sidebar section is still rendered
        # (the inner branch now drops "Add New Store" but keeps "My
        # Stores" + "Manage Subscription" so the user can navigate).
        assert b"My Stores" in r.content
        assert b"Manage Subscription" in r.content

    def test_dashboard_renders_normally_with_active_sub(
        self, tenant_with_growth_sub, user,
    ):
        """Sanity check — an active user still sees the normal dashboard
        with no subscription-needs-attention banner."""
        from django.test import Client

        self._ensure_user_membership(user, tenant_with_growth_sub.tenant)

        c = Client()
        c.force_login(user)
        r = c.get("/dashboard/")

        assert r.status_code == 200
        assert b"Your subscription is no longer active" not in r.content

    def test_dashboard_renders_normally_with_scheduled_cancel(
        self, tenant_with_growth_sub, user,
    ):
        """Scheduled cancel (``status='active' + ends_at=future``) means
        the user keeps full access — the resolver returns the sub, so
        the dashboard renders normally with no banner."""
        from django.test import Client
        from apps.subscriptions.services import cancel_subscription

        sub = tenant_with_growth_sub
        cancel_subscription(sub, cancel_at_period_end=True, actor=user)
        sub.refresh_from_db()
        assert sub.is_cancel_scheduled() is True
        self._ensure_user_membership(user, sub.tenant)

        c = Client()
        c.force_login(user)
        r = c.get("/dashboard/")

        assert r.status_code == 200
        # No needs-attention banner — the user still has active access.
        assert b"Your subscription is no longer active" not in r.content
