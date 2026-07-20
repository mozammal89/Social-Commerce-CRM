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
from .adapters.exceptions import AuthenticationError
from .constants import ConnectedAccountStatus, DeliveryStatus
from .models import ConnectedAccount, Message, Attachment
from .services import ChannelService, MessageService

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
                        # print(f"[CELERY] Event attachment: type={att.attachment_type}, url={att.external_url}")
                        pass
                message = MessageService.ingest_normalized(connected_account=account, event=event)
                if message:
                    # Direct database check for attachments
                    att_count = Attachment.objects.filter(message_id=message.id).count()
                    # print(f"[CELERY] Direct DB check: message {message.id} has {att_count} attachments")
                # ingest_normalized returns None for duplicate/empty events.
                if message is not None:
                    summary["ingested"] += 1
                else:
                    summary["skipped"] += 1
            elif isinstance(event, DeliveryUpdate):
                updated = MessageService.update_delivery_status(
                    connected_account=account,
                    update=event,
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
        "Webhook processed for account %s: %r",
        account_id,
        summary,
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
            store.id,
            retention_days,
            count,
        )

    logger.info(
        "Retention sweep done: stores_checked=%d stores_with_purge=%d messages_deleted=%d",
        stores_checked,
        stores_with_purge,
        messages_deleted,
    )
    return {
        "stores_checked": stores_checked,
        "stores_with_purge": stores_with_purge,
        "messages_deleted": messages_deleted,
    }


# ===========================================================================
# 3. Token health & refresh
# ===========================================================================
@shared_task(name="apps.messaging.tasks.validate_channel_tokens")
def validate_channel_tokens() -> dict[str, Any]:
    """Validate token health and auto-refresh expiring channel tokens.

    Runs daily via Celery beat. For every ``connected`` account:

    1. **Refresh** — if the adapter supports token refresh (e.g.
       Facebook's long-lived user → page token re-fetch), it runs first.
       Successful refresh re-arms the page token; a refresh failure marks
       the account ``expired`` (the user token is dead and cannot be
       renewed without manual re-auth).
    2. **Verify** — for accounts that could not be refreshed (no refresh
       mechanism, e.g. a raw page token), a live ``verify_credentials``
       health-check runs. A failed check marks the account ``expired``
       so the store owner is notified to reconnect.

    Returns ``{checked, refreshed, expired, healthy}`` for monitoring.
    """
    summary: dict[str, int] = {"checked": 0, "refreshed": 0, "expired": 0, "healthy": 0}

    accounts = (
        ConnectedAccount.objects.filter(status=ConnectedAccountStatus.CONNECTED.value)
        .select_related("store", "channel")
        .iterator()
    )
    for account in accounts:
        summary["checked"] += 1
        try:
            _validate_single_account(account, summary)
        except Exception:
            summary["expired"] += 1
            logger.exception(
                "Unexpected error validating tokens for account %s — marking expired",
                account.id,
            )
            ChannelService.mark_account_expired(
                account=account,
                reason="Unexpected error during token validation.",
            )

    logger.info(
        "Token validation done: checked=%d refreshed=%d expired=%d healthy=%d",
        summary["checked"],
        summary["refreshed"],
        summary["expired"],
        summary["healthy"],
    )
    return summary


def _validate_single_account(account: ConnectedAccount, summary: dict[str, int]) -> None:
    """Validate (and refresh if possible) one connected account."""
    adapter = get_adapter_for_account(account)

    # Step 1: attempt refresh. Adapters without a refresh mechanism
    # (``refresh_credentials`` returns False) fall through to verification.
    try:
        refreshed = adapter.refresh_credentials(account=account)
    except AuthenticationError as exc:
        # User token is dead — cannot refresh.
        ChannelService.mark_account_expired(
            account=account,
            reason=f"Token could not be refreshed: {exc}",
        )
        summary["expired"] += 1
        return
    except Exception:
        logger.exception("refresh_credentials raised for account %s", account.id)
        # Non-auth errors are transient (network) — don't expire yet,
        # but verify below to make a final call.
        refreshed = False

    if refreshed:
        summary["refreshed"] += 1

    # Step 2: health-check the (possibly refreshed) token via verify.
    account.refresh_from_db()
    result = adapter.verify_credentials(account=account)
    if result.valid:
        account.status = ConnectedAccountStatus.CONNECTED.value
        account.error_message = ""
        account.last_synced_at = timezone.now()
        account.save(
            update_fields=[
                "status",
                "error_message",
                "last_synced_at",
                "updated_at",
            ]
        )
        summary["healthy"] += 1
    else:
        # Token is dead and either couldn't be refreshed or refresh
        # wasn't available. Mark expired so the user reconnects.
        ChannelService.mark_account_expired(
            account=account,
            reason=result.error_message or "Token verification failed.",
        )
        summary["expired"] += 1


# ===========================================================================
# 4. Customer profile enrichment
# ===========================================================================
@shared_task(
    name="apps.messaging.tasks.enrich_customer_identity",
    autoretry_for=(Exception,),
    retry_backoff=60,
    retry_backoff_max=600,
    retry_jitter=True,
    max_retries=3,
)
def enrich_customer_identity(identity_id) -> None:
    """Fetch and apply a fresh channel profile for one customer identity.

    Thin async wrapper around :meth:`CustomerProfileService.enrich_identity`
    — the service does all the real work (adapter call, source-of-truth
    rule, propagation to the customer profile) and is idempotent + safe
    to retry.

    Triggered from two places:

    * **Lazy enrichment** — enqueued by
      :meth:`CustomerService.get_or_create_by_identity` right after a new
      identity is created, so a Facebook customer messaging for the first
      time gets a real name+avatar within seconds instead of waiting for
      the daily sync. Skipped when the webhook payload already carried a
      display_name (WhatsApp case) to avoid redundant API work.

    * **On-demand refresh** — the future
      ``POST /customers/{id}/identities/{iid}/refresh/`` endpoint.

    Adapter-side failures (network, API error, missing permission) are
    swallowed by the service (it returns ``False`` and leaves
    ``last_synced_at`` NULL so the daily batch retries). The autoretry
    here therefore only kicks in for infrastructure errors (DB down,
    broker hiccup) — exactly what we want.
    """
    from .services import CustomerProfileService

    CustomerProfileService.enrich_identity(identity_id=identity_id)


@shared_task(name="apps.messaging.tasks.sync_customer_profiles")
def sync_customer_profiles() -> dict[str, Any]:
    """Daily batch refresh of customer profiles from channel APIs.

    Walks every active store and refreshes identities whose
    ``last_synced_at`` is older than
    ``CustomerProfileService.SYNC_RESCAN_WINDOW_DAYS`` (7 days) or NULL
    (never synced — e.g. lazy enrichment in Step 4 failed or hasn't run
    yet). Delegates the per-store work to
    :meth:`CustomerProfileService.sync_store_profiles`, which already
    batches, swallows per-row errors, and respects the source-of-truth
    rule (agent-edited fields are never overwritten).

    Scheduled at 04:30 daily — after the token-validation task (04:00)
    so we only hit channel APIs with healthy tokens, and after the
    retention purge (03:00) so we don't sync profiles whose conversations
    are about to be aged out.

    Returns ``{stores_checked, stores_synced, identities_checked,
    identities_refreshed, identities_skipped, identities_failed}`` for
    monitoring/alerting.
    """
    from apps.stores.models import Store

    from .services import CustomerProfileService

    summary: dict[str, int] = {
        "stores_checked": 0,
        "stores_synced": 0,
        "identities_checked": 0,
        "identities_refreshed": 0,
        "identities_skipped": 0,
        "identities_failed": 0,
    }

    # Only sync for active, non-deleted stores. Soft-deleted or paused
    # stores are skipped — their connected accounts are typically
    # disabled too, and profile fetches would just fail with auth errors.
    store_qs = (
        Store.objects.filter(is_deleted=False, status="active")
        .values_list("id", flat=True)
        .iterator()
    )
    for store_id in store_qs:
        summary["stores_checked"] += 1
        try:
            result = CustomerProfileService.sync_store_profiles(store_id=store_id)
        except Exception:
            # A store-level failure (e.g. corrupted credentials) must not
            # abort the batch. sync_store_profiles already handles
            # per-identity exceptions; this is the outer safety net.
            logger.exception("sync_customer_profiles: store %s raised unexpectedly", store_id)
            continue

        summary["identities_checked"] += result.get("checked", 0)
        summary["identities_refreshed"] += result.get("refreshed", 0)
        summary["identities_skipped"] += result.get("skipped", 0)
        summary["identities_failed"] += result.get("failed", 0)
        if result.get("refreshed", 0) > 0:
            summary["stores_synced"] += 1

    logger.info(
        "Customer profile sync done: stores_checked=%d stores_synced=%d "
        "identities_checked=%d refreshed=%d skipped=%d failed=%d",
        summary["stores_checked"],
        summary["stores_synced"],
        summary["identities_checked"],
        summary["identities_refreshed"],
        summary["identities_skipped"],
        summary["identities_failed"],
    )
    return summary
