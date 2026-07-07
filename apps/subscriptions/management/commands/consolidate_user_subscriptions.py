"""
Heal multi-store tenants whose subscriptions diverged.

The platform's contract is one subscription per tenant. A historical
data state allows the same user to hold two (or more) active
subscriptions, one per store, often with different plans — the
``StoreCreateSerializer`` flow used to mint a new store-level sub for
every "create store" call, ignoring any pre-existing sub. The result
was that Store A reported the Free cap while Store B reported the
Growth cap, and the seat limit drifted per store instead of per
tenant.

This command walks every user, finds the highest-tier active
subscription under their ownership, promotes it to a tenant
subscription, attaches all of the user's stores to that tenant, and
deactivates the duplicate subs. The result is a single, tenant-scoped
plan that governs every store the user owns.

Idempotent and safe to re-run. Use ``--dry-run`` first.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction
from django.core.cache import cache
import logging

from apps.accounts.models import User
from apps.subscriptions.models import Subscription
from apps.stores.models import Store
from apps.subscriptions.constants import (
    CACHE_SUBSCRIPTION_PREFIX,
    STATUS_ACTIVE,
    STATUS_TRIALING,
    STATUS_CANCELED,
)
from apps.subscriptions.services import (
    get_or_create_default_tenant,
    promote_subscription_to_tenant,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Consolidate divergent per-store subscriptions into a single "
        "tenant subscription per user."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would change without writing anything.",
        )
        parser.add_argument(
            "--user-id",
            default=None,
            help="Restrict the run to a single user (UUID).",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        user_id = options.get("user_id")

        users = User.objects.all()
        if user_id:
            users = users.filter(id=user_id)

        total_healed = 0
        for user in users.iterator():
            healed = self._heal_user(user, dry_run=dry_run)
            if healed:
                total_healed += 1

        verb = "would heal" if dry_run else "healed"
        self.stdout.write(
            self.style.SUCCESS(
                f"{'DRY-RUN: ' if dry_run else ''}{total_healed} user(s) {verb}."
            )
        )

    # ------------------------------------------------------------------
    # Per-user healing
    # ------------------------------------------------------------------
    def _heal_user(self, user: User, *, dry_run: bool) -> bool:
        """Promote the user's best subscription to a tenant sub.

        Returns True if any change was made (or would be made in
        dry-run mode), False otherwise.
        """
        user_store_ids = list(
            Store.objects.filter(
                memberships__user=user,
                memberships__is_active=True,
                is_deleted=False,
            )
            .distinct()
            .values_list("id", flat=True)
        )
        if not user_store_ids:
            return False

        # The "winning" sub is the active sub with the highest
        # ``plan.price`` (most generous). Ties broken by most-recent
        # ``starts_at`` so we keep the latest intent.
        candidate_subs = list(
            Subscription.objects
            .filter(
                store_id__in=user_store_ids,
                status__in=[STATUS_ACTIVE, STATUS_TRIALING],
            )
            .exclude(plan__isnull=True)
            .select_related("plan", "store")
            .order_by("-plan__price", "-starts_at")
        )

        if not candidate_subs:
            return False

        winner = candidate_subs[0]
        losers = candidate_subs[1:]

        with transaction.atomic():
            # ``get_or_create_default_tenant`` runs an atomic insert
            # internally so concurrent heals can't double-create.
            tenant = get_or_create_default_tenant(user)

            # Promote the winning sub if it isn't tenant-attached.
            # ``promote_subscription_to_tenant`` is a no-op when the
            # sub is already tenant-scoped or has no store to anchor
            # the promotion.
            if winner.tenant_id is None:
                if winner.store_id is not None:
                    promote_subscription_to_tenant(winner, winner.store)
                else:
                    winner.tenant = tenant
                    winner.save(update_fields=["tenant", "updated_at"])

            # Bind every store to the tenant. Uses the resolved
            # tenant, not ``winner.tenant``, in case the heal path
            # created a fresh tenant for a user who had none.
            Store.objects.filter(id__in=user_store_ids).update(tenant=tenant)

            # Deactivate duplicate subs (cancel them — keeps the
            # SubscriptionEvent audit trail intact).
            loser_ids = [loser.id for loser in losers if loser.id != winner.id]
            if loser_ids:
                Subscription.objects.filter(id__in=loser_ids).update(
                    status=STATUS_CANCELED,
                )

        if dry_run:
            self.stdout.write(
                f"[DRY-RUN] user={user.id} tenant={tenant.id} "
                f"keep_sub={winner.id} ({winner.plan.slug}) "
                f"deactivate={loser_ids} "
                f"rebind_stores={user_store_ids}"
            )
            return True

        # Bust caches for every affected store and tenant so the next
        # read goes to the DB instead of a stale ``Subscription``
        # instance.
        cache_keys = [f"{CACHE_SUBSCRIPTION_PREFIX}{tenant.id}"]
        cache_keys.extend(
            f"{CACHE_SUBSCRIPTION_PREFIX}{sid}" for sid in user_store_ids
        )
        cache.delete_many(cache_keys)

        self.stdout.write(
            f"Healed user={user.id} tenant={tenant.id} "
            f"plan={winner.plan.slug} stores={len(user_store_ids)} "
            f"deactivated_subs={len(loser_ids)}"
        )
        return True
