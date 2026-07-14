"""
Celery tasks for the omnichannel messaging system.

Two concerns live here:

1. **Async webhook processing.** Platforms (Facebook, WhatsApp) require
   webhook endpoints to return ``200 OK`` within a few seconds — they
   will redeliver (and eventually throttle) otherwise. The webhook view
   therefore verifies the request synchronously, persists nothing, and
   hands the payload to ``process_webhook_payload`` to parse + ingest
   each event. One bad event never fails the batch: each is wrapped in
   its own try/except and its own transaction.

2. **Retention.** ``purge_expired_messages`` runs daily (beat) and hard-
   deletes Message rows older than the store's plan retention, capped by
   ``settings.MESSAGING_MAX_RETENTION_DAYS``. Conversations and
   customers are preserved (only chat history ages out).

Per the convention in ``apps.permissions.tasks``, each unit of work is
wrapped in its own ``transaction.atomic()`` and tasks use
``iterator()`` over querysets to keep memory bounded.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from celery import shared_task
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .adapters import get_adapter_for_account
from .adapters.dto import DeliveryUpdate, NormalizedIncomingEvent, NormalizedReactionEvent
from .constants import DeliveryStatus
from .models import ConnectedAccount, Message, Attachment
from .services import MessageService

logger = logging.getLogger(__name__)


# ===========================================================================
# 1. Webhook processing
# ===========================================================================
@shared_task(
    name="apps.messaging.tasks.process_webhook_payload",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=5,
)
def process_webhook_payload(
    *,
    account_id: str,
    headers: dict[str, str],
    body: str,
) -> dict[str, int]:
    """Parse a verified webhook body and ingest every event it carries.

    Called asynchronously from the webhook view. The body is passed as a
    string (JSON) because Celery serializes args as JSON. Each normalized
    event is ingested in its own transaction so a parse error on one item
    doesn't roll back the rest — and idempotency (the unique
    ``(connected_account, external_id)`` constraint) means redelivered
    payloads are safely no-ops.

    Returns a small ``{ingested, deliveries, skipped, failed}`` summary
    for monitoring/logging.
    """
    summary = {"ingested": 0, "deliveries": 0, "reactions": 0, "skipped": 0, "failed": 0}

    try:
        account = ConnectedAccount.objects.select_related("store", "channel").get(pk=account_id)
    except ConnectedAccount.DoesNotExist:
        logger.error("process_webhook_payload: connected account %s not found", account_id)
        return summary

    # Only connected accounts should ingest; a disconnected/error account
    # is intentionally ignored (it may be mid-reconfiguration).
    if account.status != "connected":
        logger.info("Skipping webhook for account %s (status=%s)", account_id, account.status)
        return summary

    adapter = get_adapter_for_account(account)

    # parse_webhook is the adapter's translation layer. It must not raise
    # on individual bad entries — but if it fails wholesale, we let the
    # autoretry policy handle it (platforms redeliver on non-2xx anyway).
    try:
        events = adapter.parse_webhook(headers=headers, body=body.encode("utf-8"), account=account)
    except Exception:
        logger.exception("Adapter parse_webhook failed for account %s", account_id)
        raise  # triggers autoretry

    for event in events:
        try:
            if isinstance(event, NormalizedIncomingEvent):
                if not event.has_content and not event.external_message_id:
                    summary["skipped"] += 1
                    continue
                if event.attachments:
                    for att in event.attachments:
                        print(f"[CELERY] Event attachment: type={att.attachment_type}, url={att.external_url}")
                message = MessageService.ingest_normalized(connected_account=account, event=event)
                if message:
                    # Direct database check for attachments
                    att_count = Attachment.objects.filter(message_id=message.id).count()
                    print(f"[CELERY] Direct DB check: message {message.id} has {att_count} attachments")
                # ingest_normalized returns None for duplicate/empty events.
                if message is not None:
                    summary["ingested"] += 1
                else:
                    summary["skipped"] += 1
            elif isinstance(event, DeliveryUpdate):
                updated = MessageService.update_delivery_status(
                    connected_account=account, update=event,
                )
                summary["deliveries"] += 1 if updated else 0
                if not updated:
                    summary["skipped"] += 1
            elif isinstance(event, NormalizedReactionEvent):
                applied = MessageService.apply_reaction(connected_account=account, event=event)
                summary["reactions"] = summary.get("reactions", 0) + (1 if applied else 0)
                if not applied:
                    summary["skipped"] += 1
            else:
                summary["skipped"] += 1
        except Exception as e:
            # One event failing must not abort the batch.
            summary["failed"] += 1
            import traceback
            traceback.print_exc()
            logger.exception(
                "Failed to process webhook event for account %s: %r", account_id, event
            )

    logger.info(
        "Webhook processed for account %s: %r", account_id, summary,
    )
    return summary


# ===========================================================================
# 2. Retention
# ===========================================================================
def _effective_retention_days(plan_retention_days: int | None) -> int:
    """Resolve a plan's retention into the number of days to keep.

    Semantics:
    * ``None`` → **unlimited** (the store keeps its full message history).
      Returns ``0``, which the purge task treats as "do not purge".
    * A specific value (30/60/90) → clipped to the global
      ``MESSAGING_MAX_RETENTION_DAYS`` safety cap.

    A store with no active subscription also returns ``0`` (unlimited) —
    there's no plan to derive a retention from, so we don't purge.
    """
    if plan_retention_days is None:
        return 0  # unlimited — purge task skips stores with 0
    cap = getattr(settings, "MESSAGING_MAX_RETENTION_DAYS", 90)
    return min(int(plan_retention_days), cap)


@shared_task(name="apps.messaging.tasks.purge_expired_messages")
def purge_expired_messages() -> dict[str, Any]:
    """Hard-delete messages older than each store's plan retention.

    Runs daily via Celery beat. Walks every store, resolves its active
    subscription's ``message_retention_days`` (capped by the global
    setting), and bulk-deletes the cutoff `Message` rows. Deletions
    cascade to ``Attachment`` and ``Reaction`` (FK CASCADE). Because
    media is URL-only (Phase 3 decision), there are no file bytes to
    clean up — only the row + its URL pointer.

    Conversations and Customers are deliberately preserved: only the
    message history ages out. An empty conversation remains so the
    relationship / assignment / status context isn't lost.

    Returns ``{stores_checked, stores_with_purge, messages_deleted}``.
    """
    from apps.stores.models import Store
    from apps.subscriptions.services import get_active_subscription

    now = timezone.now()
    stores_checked = 0
    stores_with_purge = 0
    messages_deleted = 0

    for store in Store.objects.filter(is_deleted=False, status="active").iterator():
        stores_checked += 1
        sub = get_active_subscription(store)
        if sub is None or sub.plan is None:
            # No active subscription → unlimited (no plan to derive
            # retention from). Don't purge.
            continue
        else:
            retention_days = _effective_retention_days(sub.plan.message_retention_days)

        # 0 = unlimited (plan has message_retention_days=None).
        if not retention_days or retention_days <= 0:
            continue

        cutoff = now - timedelta(days=retention_days)
        qs = Message.objects.filter(store=store, created_at__lt=cutoff)
        count = qs.count()
        if count == 0:
            continue

        # Delete in a transaction; CASCADE removes attachments/reactions.
        with transaction.atomic():
            deleted, _ = qs.delete()
        messages_deleted += deleted
        stores_with_purge += 1
        logger.info(
            "Retention purge: store=%s retention_days=%d deleted_messages=%d",
            store.id, retention_days, count,
        )

    logger.info(
        "Retention sweep done: stores_checked=%d stores_with_purge=%d messages_deleted=%d",
        stores_checked, stores_with_purge, messages_deleted,
    )
    return {
        "stores_checked": stores_checked,
        "stores_with_purge": stores_with_purge,
        "messages_deleted": messages_deleted,
    }
