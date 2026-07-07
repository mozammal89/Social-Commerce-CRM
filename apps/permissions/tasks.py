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
    from apps.subscriptions.models import Subscription
    from apps.subscriptions.services import transition_status
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
    from apps.subscriptions.models import Subscription
    from apps.subscriptions.services import transition_status
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
    from apps.subscriptions.models import Subscription
    from apps.subscriptions.services import transition_status
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
