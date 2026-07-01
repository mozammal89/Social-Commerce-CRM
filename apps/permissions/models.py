"""
Database models for the RBAC system.

All models use the existing abstract bases from apps.common.models.

Entity overview:

  Resource ──*── Permission
  Role     ──*── RolePermission ──*── Permission
  User     ──*── StoreMembership ──*── Store
  User     ──*── UserPermissionOverride ──*── Permission
  SubscriptionPlan ──*── PlanFeature ──*── Feature
  Store    ──1──1 Subscription ──*── SubscriptionPlan
  Subscription ──*── SubscriptionEvent
  AuditLog (append-only)

Notes:
- Role is "system" when store IS NULL, "custom" when store is set.
- RolePermission.modifier is GRANT / DEFAULT / DENY; DENY beats GRANT
  in the resolver to prevent privilege escalation.
- UserPermissionOverride.is_granted=False is an absolute DENY.
"""

from __future__ import annotations

import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.common.models import UUIDModel, TimeStampedModel

from .constants import (
    ACTION_CHOICES,
    MODIFIER_CHOICES,
    SUBSCRIPTION_STATUS_CHOICES,
    MODIFIER_GRANT,
)
from .exceptions import AuditLogImmutable


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------
class Resource(UUIDModel, TimeStampedModel):
    """
    A 'thing' the system protects. Examples: customers, products, orders.

    One Resource × N Actions = N Permission rows. The DB mirrors what the
    registry declares; ``sync_permissions`` is the source of truth.
    """

    code = models.CharField(
        max_length=64,
        unique=True,
        help_text=_("Stable code, lowercase, e.g. 'customers'."),
    )
    name = models.CharField(max_length=128)
    category = models.CharField(max_length=64, db_index=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    # JSON list of supported actions; the registry is the source of truth,
    # but this column lets ops disable an action without touching code.
    actions = models.JSONField(
        default=list,
        blank=True,
        help_text=_("List of action codes e.g. ['view','create','update']."),
    )

    class Meta:
        ordering = ("category", "code")
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["category", "is_active"]),
        ]

    def __str__(self) -> str:
        return f"{self.code} ({self.name})"


# ---------------------------------------------------------------------------
# Permission
# ---------------------------------------------------------------------------
class Permission(UUIDModel, TimeStampedModel):
    """
    Action × Resource. Code format: '<resource>.<action>'.

    Examples: customers.view, orders.create, reports.export.
    """

    code = models.CharField(
        max_length=96,
        unique=True,
        help_text=_("e.g. 'customers.view'."),
    )
    resource = models.ForeignKey(
        Resource,
        on_delete=models.CASCADE,
        related_name="permissions",
    )
    action = models.CharField(max_length=16, choices=ACTION_CHOICES)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True)
    is_system = models.BooleanField(
        default=True,
        help_text=_("System permissions cannot be deleted by store admins."),
    )

    class Meta:
        ordering = ("code",)
        constraints = [
            models.UniqueConstraint(
                fields=["resource", "action"],
                name="uniq_perm_resource_action",
            ),
        ]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["resource", "action"]),
        ]

    def __str__(self) -> str:
        return self.code

    def save(self, *args, **kwargs):
        # Auto-derive the code if not provided.
        if not self.code and self.resource_id:
            self.code = f"{self.resource.code}.{self.action}"
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Role
# ---------------------------------------------------------------------------
class Role(UUIDModel, TimeStampedModel):
    """
    A bundle of permissions.

    Two flavors:
      - System roles: store IS NULL, is_system=True.
        Globally defined (e.g. 'Store Owner'). Created by seeders,
        not deletable.
      - Custom roles: store FK set, is_system=False.
        Per-store bespoke. Clonable from any role.

    Hierarchy is encoded by 'level' (higher = more authority) but
    inheritance is explicit via inherits_from — not implicit by level.
    """

    LEVEL_OWNER = 100
    LEVEL_ADMIN = 80
    LEVEL_MANAGER = 60
    LEVEL_STAFF = 40
    LEVEL_VIEWER = 20
    LEVEL_CUSTOM = 0

    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128)
    description = models.TextField(blank=True)

    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="custom_roles",
        null=True,
        blank=True,
        help_text=_("NULL for system roles; set for per-store custom roles."),
    )
    is_system = models.BooleanField(
        default=False,
        help_text=_("System roles cannot be deleted; cloning is allowed."),
    )
    level = models.PositiveSmallIntegerField(default=LEVEL_CUSTOM)
    is_active = models.BooleanField(default=True)
    inherits_from = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
        help_text=_("Optional parent role for inheritance."),
    )

    class Meta:
        ordering = ("-level", "name")
        constraints = [
            models.UniqueConstraint(
                fields=["store", "slug"],
                name="uniq_role_store_slug",
            ),
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(store__isnull=True),
                name="uniq_role_system_slug",
            ),
        ]
        indexes = [
            models.Index(fields=["store", "is_active"]),
            models.Index(fields=["level"]),
        ]

    def __str__(self) -> str:
        suffix = "" if self.store_id else " (system)"
        return f"{self.name}{suffix}"


# ---------------------------------------------------------------------------
# RolePermission
# ---------------------------------------------------------------------------
class RolePermission(UUIDModel, TimeStampedModel):
    """
    Through table between Role and Permission.

    The ``modifier`` field encodes GRANT/DEFAULT/DENY so that:
      - Role A grants 'orders.delete'
      - Role B denies 'orders.delete'
      - User has both roles → DENY wins.
    """

    role = models.ForeignKey(
        Role,
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="role_bindings",
    )
    modifier = models.CharField(
        max_length=8,
        choices=MODIFIER_CHOICES,
        default=MODIFIER_GRANT,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["role", "permission"],
                name="uniq_role_permission",
            ),
        ]
        indexes = [
            models.Index(fields=["role", "permission"]),
        ]

    def __str__(self) -> str:
        return f"{self.role}/{self.permission.code}={self.modifier}"


# ---------------------------------------------------------------------------
# StoreMembership
# ---------------------------------------------------------------------------
class StoreMembership(UUIDModel, TimeStampedModel):
    """
    User ↔ Store ↔ Role binding.

    Replaces Store.owners/managers/staff M2Ms over time. During the
    cutover window, both sources are populated; Store.is_owner() etc.
    delegate here as the source of truth.
    """

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="store_memberships",
    )
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name="memberships",
    )

    is_active = models.BooleanField(default=True)
    joined_at = models.DateTimeField(auto_now_add=True)
    invited_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invitations_sent",
    )
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "store", "role"],
                name="uniq_membership_user_store_role",
            ),
        ]
        indexes = [
            models.Index(fields=["store", "is_active"]),
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["store", "role"]),
        ]
        ordering = ("-joined_at",)

    def __str__(self) -> str:
        return f"{self.user_id}@{self.store_id} as {self.role.name}"

    def is_current(self) -> bool:
        """Active and not expired."""
        if not self.is_active:
            return False
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        return True


# ---------------------------------------------------------------------------
# UserPermissionOverride
# ---------------------------------------------------------------------------
class UserPermissionOverride(UUIDModel, TimeStampedModel):
    """
    Explicit grant/deny for a single user, optionally scoped to a store
    and optionally time-boxed.

    DENY overrides are absolute. If is_granted=False, the user can never
    perform this action in this store, regardless of role.
    """

    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="permission_overrides",
    )
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.CASCADE,
        related_name="user_overrides",
        null=True,
        blank=True,
        help_text=_("NULL = applies across all stores the user is a member of."),
    )
    permission = models.ForeignKey(
        Permission,
        on_delete=models.CASCADE,
        related_name="user_overrides",
    )

    is_granted = models.BooleanField(
        help_text=_("True = grant, False = deny. DENY is absolute."),
    )
    reason = models.CharField(max_length=255, blank=True)
    granted_by = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="overrides_granted",
    )
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "store", "permission"],
                name="uniq_user_perm_override",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "permission"]),
            models.Index(fields=["expires_at"]),
        ]
        ordering = ("-created_at",)

    def is_active(self) -> bool:
        """Active and not expired."""
        if self.expires_at and self.expires_at <= timezone.now():
            return False
        return True

    def __str__(self) -> str:
        sign = "+" if self.is_granted else "-"
        return f"{sign}{self.permission.code} → {self.user_id}"


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
        Feature,
        through="PlanFeature",
        related_name="plans",
    )

    max_users = models.PositiveIntegerField(default=5)
    max_stores = models.PositiveIntegerField(default=1)
    max_products = models.PositiveIntegerField(default=500)
    max_orders_per_month = models.PositiveIntegerField(default=1000)
    max_warehouses = models.PositiveIntegerField(default=1)

    is_active = models.BooleanField(default=True)
    is_public = models.BooleanField(
        default=True,
        help_text=_("Hide internal/legacy plans from the catalog."),
    )
    sort_order = models.PositiveSmallIntegerField(default=100)
    trial_days = models.PositiveSmallIntegerField(default=14)

    class Meta:
        ordering = ("sort_order", "price")

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
        SubscriptionPlan,
        on_delete=models.CASCADE,
        related_name="plan_features",
    )
    feature = models.ForeignKey(
        Feature,
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
        SubscriptionPlan,
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

    stripe_customer_id = models.CharField(max_length=64, blank=True)
    stripe_subscription_id = models.CharField(max_length=64, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["status"]),
            models.Index(fields=["current_period_end"]),
        ]

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


# ---------------------------------------------------------------------------
# SubscriptionEvent
# ---------------------------------------------------------------------------
class SubscriptionEvent(UUIDModel, TimeStampedModel):
    """
    Append-only event log: created, renewed, upgraded, canceled, payment_failed.
    """

    subscription = models.ForeignKey(
        Subscription,
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

    def __str__(self) -> str:
        return f"{self.subscription_id}: {self.event_type}"


# ---------------------------------------------------------------------------
# AuditLog
# ---------------------------------------------------------------------------
class AuditLog(UUIDModel):
    """
    Append-only audit record. No update/delete is permitted in code or admin.

    Why not TimeStampedModel? We intentionally don't expose 'updated_at' on
    an append-only log; the only timestamp we want is 'created_at' = when
    the event happened.
    """

    actor = models.ForeignKey(
        "accounts.User",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    store = models.ForeignKey(
        "stores.Store",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )

    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64, db_index=True)
    target_id = models.CharField(max_length=64, db_index=True)

    # DjangoJSONEncoder is required because ``model_to_dict`` returns raw
    # ``datetime``/``Decimal``/``UUID`` values which the default JSON
    # encoder cannot serialize. Without this, AuditLog rows for any model
    # that contains non-JSON-native fields (e.g. Subscription) would fail
    # to persist whenever the row is updated.
    before = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)
    after = models.JSONField(null=True, blank=True, encoder=DjangoJSONEncoder)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    request_id = models.CharField(max_length=64, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [
            models.Index(fields=["actor", "created_at"]),
            models.Index(fields=["store", "created_at"]),
            models.Index(fields=["target_type", "target_id"]),
        ]

    def __str__(self) -> str:
        return (
            f"{self.action} {self.target_type}#{self.target_id} @ {self.created_at:%Y-%m-%d %H:%M}"
        )

    def save(self, *args, **kwargs):
        # AuditLog is append-only. We detect a re-save via Django's
        # _state.adding flag: it's True for a new (uncommitted) instance
        # and False once the row has been fetched or persisted.
        if not self._state.adding:
            raise AuditLogImmutable()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AuditLogImmutable()
