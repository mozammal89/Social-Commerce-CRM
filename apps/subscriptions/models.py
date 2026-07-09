"""
Subscription models for billing and plan management.

These models were moved from apps.permissions.models as part of an
architecture refactoring to properly separate concerns.
"""

from __future__ import annotations

import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.models import UUIDModel, TimeStampedModel

# Import subscription-related constants from permissions app
# This maintains compatibility during the migration
from apps.permissions.constants import SUBSCRIPTION_STATUS_CHOICES


# ---------------------------------------------------------------------------
# Feature
# ---------------------------------------------------------------------------
class Feature(UUIDModel, TimeStampedModel):
    """
    A billing-tier capability. Examples: marketing_campaigns, multi_warehouse.

    Features are gated by subscription plans and surface as boolean
    checks via `user.has_feature(code)` and `store.has_feature(code)`.
    """

    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=64, db_index=True)

    class Meta:
        ordering = ("category", "code")
        db_table = "permissions_feature"

    def __str__(self) -> str:
        return self.code


# ---------------------------------------------------------------------------
# SubscriptionPlan
# ---------------------------------------------------------------------------
class SubscriptionPlan(UUIDModel, TimeStampedModel):
    """
    A billing tier (Starter / Growth / Professional / Enterprise) with
    bundled Features and numeric limits.
    """

    class BillingPeriod(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    name = models.CharField(max_length=64)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")
    billing_period = models.CharField(
        max_length=8,
        choices=BillingPeriod.choices,
        default=BillingPeriod.MONTHLY,
    )

    features = models.ManyToManyField(
        "subscriptions.Feature",
        through="subscriptions.PlanFeature",
        related_name="plans",
    )

    max_users = models.PositiveIntegerField(default=5)
    max_stores = models.PositiveIntegerField(default=1)
    max_products = models.PositiveIntegerField(default=500)
    max_orders_per_month = models.PositiveIntegerField(default=1000)
    max_warehouses = models.PositiveIntegerField(default=1)
    # Omnichannel messaging: how long a store on this plan keeps its
    # message history. A daily Celery beat task hard-purges Message rows
    # (and cascaded attachments/reactions) older than this for each store.
    # ``None`` = unlimited (subject to the global MESSAGING_MAX_RETENTION_DAYS
    # safety cap in settings). Typical tiers: 30 / 60 / 90 days.
    message_retention_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_("Message history retention in days. NULL = unlimited (capped by MESSAGING_MAX_RETENTION_DAYS)."),
    )

    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(
        default=True,
        help_text=_("Hide internal/legacy plans from the catalog."),
    )
    sort_order = models.PositiveSmallIntegerField(default=100)
    trial_days = models.PositiveSmallIntegerField(default=14)

    class Meta:
        ordering = ("sort_order", "price")
        db_table = "permissions_subscriptionplan"

    def __str__(self) -> str:
        return self.name


# ---------------------------------------------------------------------------
# PlanFeature
# ---------------------------------------------------------------------------
class PlanFeature(UUIDModel, TimeStampedModel):
    """
    Through table linking Plan <-> Feature, with an optional numeric limit.

    Example: plan=Starter, feature=marketing_campaigns, limit_value=1
    (1 active campaign).
    """

    plan = models.ForeignKey(
        "subscriptions.SubscriptionPlan",
        on_delete=models.CASCADE,
        related_name="plan_features",
    )
    feature = models.ForeignKey(
        "subscriptions.Feature",
        on_delete=models.CASCADE,
        related_name="plan_features",
    )
    limit_value = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_("NULL = unlimited within the feature."),
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["plan", "feature"],
                name="uniq_plan_feature",
            ),
        ]
        db_table = "permissions_planfeature"

    def __str__(self) -> str:
        return f"{self.plan.slug}/{self.feature.code}"


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------
class Subscription(UUIDModel, TimeStampedModel):
    """
    Per-tenant billing state. One active subscription per tenant.

    Changed from store-based to tenant-based subscription model.
    All stores under a tenant inherit the tenant's subscription limits.
    """

    # Temporary: keep store field for migration, will be removed later
    store = models.OneToOneField(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="subscription",
        null=True,  # Temporarily nullable for migration
        blank=True,
    )

    # New tenant field - will become primary after migration
    tenant = models.OneToOneField(
        "accounts.Tenant",
        on_delete=models.CASCADE,
        related_name="subscription",
        null=True,  # Allow null temporarily for migration
        blank=True,
    )
    plan = models.ForeignKey(
        "subscriptions.SubscriptionPlan",
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=12,
        choices=SUBSCRIPTION_STATUS_CHOICES,
        default="trialing",
    )

    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)

    stripe_customer_id = models.CharField(max_length=64, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=64, blank=True, null=True)

    # Arbitrary JSON storage used by service-layer flows that need to
    # record transient state on the subscription (e.g. a scheduled
    # downgrade that hasn't taken effect yet, pending metadata for the
    # Stripe sync, etc). Default empty dict so callers don't have to
    # special-case the unset state.
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["current_period_end"]),
        ]
        db_table = "permissions_subscription"

    def __str__(self) -> str:
        """Display either tenant or store for migration period."""
        if self.tenant:
            target = f"Tenant:{self.tenant_id}"
        elif self.store:
            target = f"Store:{self.store_id}"
        else:
            target = "No target"
        return f"{target} → {self.plan.slug} ({self.status})"

    def is_active(self) -> bool:
        """Active or in-trial, not past period end."""
        now = timezone.now()
        if self.status == "active":
            if self.current_period_end and self.current_period_end < now:
                return False
            return True
        if self.status == "trialing":
            return self.trial_ends_at is None or self.trial_ends_at > now
        return False

    def is_cancel_scheduled(self) -> bool:
        """True if the user has scheduled a cancel-at-period-end that
        has not yet elapsed.

        Detected purely from the row state — no separate flag column:
        ``cancel_subscription(cancel_at_period_end=True)`` sets
        ``ends_at == current_period_end`` while leaving ``status == 'active'``.

        Returns False when:
          - ``status`` is not ``active`` (trialing / canceled / past_due
            subs use other state paths; trial cancel goes through
            ``transition_status`` and never sets ``ends_at``), or
          - ``ends_at`` is None (no cancel ever requested), or
          - ``ends_at`` is in the past (the period already elapsed;
            ``is_active()`` will independently return False).

        The single source of truth for the manage-page banner and the
        Reactivate-button visibility — both the view context and the
        ``reactivate_subscription`` service read this method so the row
        state and the UI can't drift out of sync.
        """
        return (
            self.status == "active"
            and self.ends_at is not None
            and self.ends_at > timezone.now()
        )

    def is_canceled_or_canceling(self) -> bool:
        """True if the subscription is in *any* canceled state.

        Broader than ``is_cancel_scheduled`` — covers both:
          - the scheduled-cancel path (``status='active'`` +
            ``ends_at`` set, still has access until period end), and
          - the immediate-cancel path (``status='canceled'`` —
            ``cancel_subscription(cancel_at_period_end=True)`` on a
            non-active sub, or ``cancel_at_period_end=False``).

        The manage-page banner uses this so *every* cancel action
        produces visible feedback, regardless of which code branch
        ran. The narrower ``is_cancel_scheduled`` is still the gate
        for the Reactivate button, since reversing a fully-canceled
        sub needs a different flow (``transition_status(canceled →
        active)``) than the one ``reactivate_subscription`` implements.
        """
        if self.status == "canceled":
            return True
        return self.is_cancel_scheduled()


# ---------------------------------------------------------------------------
# SubscriptionEvent
# ---------------------------------------------------------------------------
class SubscriptionEvent(UUIDModel, TimeStampedModel):
    """
    Append-only event log: created, renewed, upgraded, canceled, payment_failed.
    """

    subscription = models.ForeignKey(
        "subscriptions.Subscription",
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(max_length=32, db_index=True)
    occurred_at = models.DateTimeField()
    metadata = models.JSONField(default=dict, blank=True)
    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="subscription_events",
    )

    class Meta:
        ordering = ("-occurred_at",)
        indexes = [
            models.Index(fields=["subscription", "occurred_at"]),
        ]
        db_table = "permissions_subscriptionevent"

    def __str__(self) -> str:
        return f"{self.subscription_id}: {self.event_type}"
