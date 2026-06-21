# Subscription Module — Implementation Spec

**Audience:** Developer applying these changes.
**Scope:** Two gaps from the subscription audit.
**Out of scope:** Plan catalog/pricing endpoint, signup-time subscription creation, full aamarpay checkout flow (mentioned briefly at the end for context).

---

## 1. `max_users` enforcement in `manage_store_staff`

### Goal
Block `add_member` once the store's active plan reaches `max_users`. Owners see a clear error; nothing else changes.

### Current behavior (audit)
- `apps/stores/views.py:209` calls `add_member(target_user, store, role, invited_by=user)` directly.
- `add_member` (`apps/permissions/services.py:137`) is idempotent on `(user, store, role)` and reactivates a soft-deleted membership.
- `assert_within_plan_limit(store, limit_attr, current_value)` (`services.py:116`) raises `PlanLimitExceeded` when `current_value >= cap`.

### Design decision
- **Count only "real" seats.** Count active `StoreMembership` rows where the membership is **not** `canceled`-equivalent — i.e. `is_active=True`. We're already using `is_active` as the soft-delete flag.
- **Skip when re-activating.** If the user is already a member (`is_active=False`), flipping them back on does not increase seat count. So the guard runs **only when a brand-new membership is created**.
- **Count before membership create.** Read the current count, call `assert_within_plan_limit`, then create. We avoid transactions-around-counting issues because `StoreMembership.objects.get_or_create` is atomic — but counting first is the right ordering.
- **Superusers bypass** (consistent with the rest of the codebase — `views.py:75` etc.).

### Edits

**File:** `apps/stores/views.py`

In `manage_store_staff`, before calling `add_member`, replace:

```python
if serializer.validated_data["action"] == "add":
    add_member(target_user, store, role, invited_by=user)
    message = f"User added as {role.name}"
else:
    remove_member(target_user, store, role)
    message = f"User removed as {role.name}"
```

with:

```python
action = serializer.validated_data["action"]
if action == "add":
    # max_users enforcement: only count when this is a new membership.
    existing = StoreMembership.objects.filter(
        user=target_user, store=store, role=role,
    ).first()
    if existing is None or not existing.is_active:
        from apps.permissions.services import assert_within_plan_limit
        current_seats = StoreMembership.objects.filter(
            store=store, is_active=True,
        ).count()
        assert_within_plan_limit(store, "max_users", current_seats)
    add_member(target_user, store, role, invited_by=user)
    message = f"User added as {role.name}"
else:
    remove_member(target_user, store, role)
    message = f"User removed as {role.name}"
```

### Edge cases & decisions

| Case | Behavior |
|---|---|
| Store has no `Subscription` row | `assert_within_plan_limit` raises `PlanLimitExceeded` with cap=0 → blocks all adds. This matches the rest of the codebase. If you want a "trial default" path later, mirror `_resolve_max_stores_cap`. |
| Subscription exists but `is_active()` returns False (canceled/expired/past_due) | Same as above — blocked. Correct: features/limits are revoked. |
| `max_users = 0` on a plan (misconfigured) | All adds blocked. Add a data-validation check on `SubscriptionPlan` if you want; otherwise, log and admin-correct. |
| Same role re-added to the same user (idempotent) | No seat cost — handled by `existing.is_active=False` branch. |
| Same user with **different** role in same store | Counts as a new seat. Correct: seat = user, not membership. If you prefer seat = membership, change the count to include `(user, role)` distinct pairs. **Decide now.** The plan field is named `max_users`, suggesting seat = user, so the spec above counts by user (via `StoreMembership` rows where `is_active=True`). |
| Owner adds themselves | Trivially passes (already a member). |

### Tests to add

In `apps/permissions/tests/test_subscription.py` (or a new `tests/test_max_users.py`):

1. Adding a member when at cap raises `PlanLimitExceeded` with HTTP 403/400 mapping.
2. Re-activating a previously deactivated membership does not raise.
3. Adding to a different role when at `max_users - 1` passes (1 seat left).
4. `past_due` subscription blocks adds.
5. Superuser bypasses.

---

## 2. Status lifecycle: Celery beat + `SubscriptionEvent` writer

### Goal
Auto-transition `Subscription.status` based on time, and write a `SubscriptionEvent` row for every transition. Replace ad-hoc status manipulation with one service: `transition_status()`.

### State machine

```
                     create
                       │
                       ▼
                  ┌──────────┐ trial_ends_at < now
                  │ trialing │──────────────────────┐
                  └──────────┘                       │
                       │                             ▼
            payment succeeded                  ┌──────────┐
                       │                       │ expired  │
                       ▼                       └──────────┘
                  ┌──────────┐ current_period_end < now
                  │  active  │──────────────────────┐
                  └──────────┘                       │
                       │ payment_failed              │
                       ▼                             ▼
                  ┌──────────┐ grace_period_end < now
                  │ past_due │──────────────────────┐
                  └──────────┘                       │
                       │                            │
                       └─────────────┬──────────────┘
                                     │
                       reactivated   │   user cancels
                                     ▼
                                ┌──────────┐
                                │ canceled │
                                └──────────┘
```

### Status semantics (documented)

| Status | `is_active()` returns | Features usable | Writes allowed |
|---|---|---|---|
| `trialing` | Yes (until `trial_ends_at`) | Yes | Yes |
| `active` | Yes (until `current_period_end`) | Yes | Yes |
| `past_due` | **No** | No | Yes (grace period) |
| `canceled` | No | No | No (read-only) |
| `expired` | No | No | No |

The current `Subscription.is_active()` returns False for `past_due`, which is the same as canceled/expired. **Spec:** add a separate `is_in_grace_period()` helper later if business wants past_due to allow writes; for now keep the strict behavior (consistent with the rest of the codebase).

### Design

#### 2.1 `record_event()` helper

Add to `apps/permissions/services.py`:

```python
def record_event(subscription, event_type: str, *, actor=None, metadata: dict | None = None) -> "SubscriptionEvent":
    from .models import SubscriptionEvent
    return SubscriptionEvent.objects.create(
        subscription=subscription,
        event_type=event_type,
        occurred_at=timezone.now(),
        actor=actor,
        metadata=metadata or {},
    )
```

Add an `EVENT_*` constant block in `apps/permissions/constants.py`:

```python
EVENT_TRIAL_EXPIRED = "trial.expired"
EVENT_PERIOD_EXPIRED = "period.expired"
EVENT_PAYMENT_FAILED = "payment.failed"
EVENT_CANCELED = "subscription.canceled"
EVENT_REACTIVATED = "subscription.reactivated"
EVENT_RENEWED = "subscription.renewed"
EVENT_CREATED = "subscription.created"
EVENT_PLAN_CHANGED = "plan.changed"
```

#### 2.2 `transition_status()` — single source of truth

Add to `apps/permissions/services.py`:

```python
def transition_status(
    subscription: "Subscription",
    new_status: str,
    *,
    actor=None,
    reason: str | None = None,
    metadata: dict | None = None,
) -> bool:
    """
    Move a subscription to `new_status` if not already there.

    Writes a SubscriptionEvent. Returns True iff the status actually changed.

    `reason` is recorded in metadata; the canonical event_type is mapped
    from the (old → new) transition so the event log is self-describing.
    """
    from .models import SubscriptionEvent
    from .constants import (
        SUB_TRIALING, SUB_ACTIVE, SUB_PAST_DUE, SUB_CANCELED, SUB_EXPIRED,
        EVENT_RENEWED, EVENT_TRIAL_EXPIRED, EVENT_PERIOD_EXPIRED,
        EVENT_PAYMENT_FAILED, EVENT_CANCELED as EVT_CANCELED,
    )

    if subscription.status == new_status:
        return False

    old = subscription.status
    subscription.status = new_status

    # Map transition to canonical event_type.
    transition = (old, new_status)
    event_type_map = {
        (SUB_TRIALING, SUB_ACTIVE): EVENT_RENEWED,
        (SUB_TRIALING, SUB_EXPIRED): EVENT_TRIAL_EXPIRED,
        (SUB_ACTIVE, SUB_PAST_DUE): EVENT_PAYMENT_FAILED,
        (SUB_ACTIVE, SUB_EXPIRED): EVENT_PERIOD_EXPIRED,
        (SUB_PAST_DUE, SUB_EXPIRED): EVENT_PERIOD_EXPIRED,
        (SUB_ACTIVE, SUB_CANCELED): EVT_CANCELED,
        (SUB_TRIALING, SUB_CANCELED): EVT_CANCELED,
        (SUB_PAST_DUE, SUB_CANCELED): EVT_CANCELED,
    }
    event_type = event_type_map.get(transition, f"transition.{old}_to_{new_status}")

    payload = {"from": old, "to": new_status}
    if reason:
        payload["reason"] = reason
    if metadata:
        payload.update(metadata)

    subscription.save(update_fields=["status", "updated_at"])
    SubscriptionEvent.objects.create(
        subscription=subscription,
        event_type=event_type,
        occurred_at=timezone.now(),
        actor=actor,
        metadata=payload,
    )
    return True
```

#### 2.3 Celery tasks

**New file:** `apps/permissions/tasks.py`

```python
"""Celery tasks for subscription lifecycle.

Scheduled via Celery beat in config/celery.py.
"""
from __future__ import annotations
import logging
from celery import shared_task
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


@shared_task(name="apps.permissions.tasks.expire_trials")
def expire_trials() -> int:
    """Move trialing subscriptions whose trial_ends_at < now to expired."""
    from .models import Subscription
    from .services import transition_status
    from .constants import SUB_TRIALING, SUB_EXPIRED

    now = timezone.now()
    qs = Subscription.objects.filter(
        status=SUB_TRIALING,
        trial_ends_at__lt=now,
    )
    count = 0
    for sub in qs.iterator():
        with transaction.atomic():
            transition_status(sub, SUB_EXPIRED, reason="trial_ended")
            count += 1
    logger.info("Expired %d trials", count)
    return count


@shared_task(name="apps.permissions.tasks.expire_active_periods")
def expire_active_periods() -> int:
    """Move active subscriptions whose current_period_end < now to expired."""
    from .models import Subscription
    from .services import transition_status
    from .constants import SUB_ACTIVE, SUB_EXPIRED

    now = timezone.now()
    qs = Subscription.objects.filter(
        status=SUB_ACTIVE,
        current_period_end__lt=now,
    )
    count = 0
    for sub in qs.iterator():
        with transaction.atomic():
            transition_status(sub, SUB_EXPIRED, reason="period_ended")
            count += 1
    logger.info("Expired %d active subscriptions", count)
    return count


@shared_task(name="apps.permissions.tasks.escalate_past_due")
def escalate_past_due(grace_days: int = 7) -> int:
    """Move past_due subscriptions older than grace_days to expired.

    Idempotent: only acts on rows currently past_due.
    """
    from datetime import timedelta
    from .models import Subscription
    from .services import transition_status
    from .constants import SUB_PAST_DUE, SUB_EXPIRED

    cutoff = timezone.now() - timedelta(days=grace_days)
    # Need an event-time proxy — use updated_at as the "marked past_due at" time.
    qs = Subscription.objects.filter(
        status=SUB_PAST_DUE,
        updated_at__lt=cutoff,
    )
    count = 0
    for sub in qs.iterator():
        with transaction.atomic():
            transition_status(sub, SUB_EXPIRED, reason="grace_period_elapsed")
            count += 1
    logger.info("Escalated %d past_due subscriptions", count)
    return count
```

#### 2.4 Wire into `apps/permissions/apps.py`

Make sure tasks module is imported (auto-discovery picks up `@shared_task`, but explicit import is safer if you don't have `autodiscover_tasks` configured for this app). Verify `apps/permissions/apps.py` has either:

- `app.autodiscover_tasks()` call, OR
- explicit `from . import tasks` in `ready()`.

If neither, add `from . import tasks` inside `ready()` to ensure signal and task registration both run.

#### 2.5 Schedule in `config/celery.py`

In `app.conf.beat_schedule`, add:

```python
"expire-trials-hourly": {
    "task": "apps.permissions.tasks.expire_trials",
    "schedule": crontab(minute=15),  # every hour at :15
},
"expire-active-periods-hourly": {
    "task": "apps.permissions.tasks.expire_active_periods",
    "schedule": crontab(minute=30),  # every hour at :30
},
"escalate-past-due-daily": {
    "task": "apps.permissions.tasks.escalate_past_due",
    "schedule": crontab(hour=2, minute=0),  # 02:00 daily
    "kwargs": {"grace_days": 7},
},
```

(Don't drop the existing `cleanup-refresh-tokens`.)

### Edge cases & decisions

| Case | Behavior |
|---|---|
| `trial_ends_at` is NULL | Skip — `is_active()` already returns True for trialing without an end. Tasks filter on `trial_ends_at__lt=now`, so NULL rows are not picked up. |
| `current_period_end` is NULL | Same — `Subscription.is_active()` returns True unconditionally for `active` if NULL. Tasks filter on `current_period_end__lt=now`, so NULL rows are not picked up. Acceptable, but make the onboarding path always set these. |
| Race: two workers pick the same row | `transition_status` is idempotent (returns False if no change). The `update_fields` saves only `status` + `updated_at`, so concurrent transitions are safe-ish; the last writer wins. For stronger guarantees, use `Subscription.objects.filter(pk=sub.pk, status=old).update(status=new)` and check rowcount. |
| `past_due` has no separate `marked_past_due_at` column | The task uses `updated_at` as a proxy. **Decision:** acceptable for v1, but if you want a real timestamp, add a field and a data migration. |
| Cron beats at the same instant across multiple workers | Each task is idempotent. Use `CELERY_TASK_ALWAYS_EAGER=False` in prod and run with a single beat instance (default). |
| `past_due` set externally (aamarpay IPN) | Out of scope here; in `aamarpay` webhook, call `transition_status(sub, SUB_PAST_DUE, actor=..., metadata={"ref_id": "..."})`. |
| Cancel | Add a thin endpoint that calls `transition_status(sub, SUB_CANCELED, actor=request.user, reason="user_initiated")`. The `manage_store_staff`-style endpoint pattern fits. |
| Reactivation (canceled → active) | Not modeled here. Requires a payment event. Plan for v2. |

### Tests to add

In `apps/permissions/tests/test_subscription.py`:

1. `record_event` writes a row with the right event_type and metadata.
2. `transition_status` writes a row even when the status doesn't actually change? **No** — return False and skip. Test this.
3. `transition_status` from `trialing → active` records `EVENT_RENEWED`.
4. `transition_status` from `active → past_due` records `EVENT_PAYMENT_FAILED`.
5. `transition_status` from `past_due → expired` records `EVENT_PERIOD_EXPIRED`.
6. `expire_trials` task picks up only `trialing` rows with `trial_ends_at < now`.
7. `expire_active_periods` task picks up only `active` rows with `current_period_end < now`.
8. `escalate_past_due` task picks up only `past_due` rows older than `grace_days`.
9. Tasks are idempotent — running twice in a row doesn't double-write events.

---

## 3. Brief: where aamarpay fits (out of scope, FYI)

The model already has `stripe_customer_id`/`stripe_subscription_id` columns. For aamarpay:

- Rename to `aamarpay_customer_id` / `aamarpay_trxid` in a future migration (or keep generic names; aamarpay uses `tran_id` per transaction, not a persistent customer ID like Stripe).
- Add `apps/payments/aamarpay.py` with a verify-IPN endpoint and a `mark_paid(tran_id)` helper.
- The `transition_status(sub, SUB_ACTIVE, actor=None, metadata={"tran_id": ...})` call goes inside the IPN handler — using the helper from §2.2 above.
- No SDK needed; aamarpay is plain HTTP POST. Add `requests` (already in your stack via Django's dependencies) — or use stdlib `urllib` if you want zero new deps.

---

## 4. File-by-file change summary

| File | Change |
|---|---|
| `apps/stores/views.py` | Add `max_users` guard in `manage_store_staff` (§1) |
| `apps/permissions/constants.py` | Add `EVENT_*` constants (§2.1) |
| `apps/permissions/services.py` | Add `record_event()` and `transition_status()` (§2.1, §2.2) |
| `apps/permissions/tasks.py` | **New file** with three Celery tasks (§2.3) |
| `apps/permissions/apps.py` | Ensure tasks imported in `ready()` (§2.4) |
| `config/celery.py` | Add three beat schedule entries (§2.5) |
| `apps/permissions/tests/test_subscription.py` | New tests for both areas (§1 tests, §2 tests) |

---

## 5. Migration? No.

`SubscriptionPlan.max_users` and `Subscription.status` already exist. `SubscriptionEvent` already exists. No schema change is required for either area. Just code + Celery schedule.
