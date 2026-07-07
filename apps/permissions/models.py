"""
Database models for the RBAC system.

All models use the existing abstract bases from apps.common.models.

Entity overview:

  Resource ──*── Permission
  Role     ──*── RolePermission ──*── Permission
  User     ──*── StoreMembership ──*── Store
  User     ──*── UserPermissionOverride ──*── Permission
  AuditLog (append-only)

Subscription-related models (Feature, SubscriptionPlan, PlanFeature, Subscription,
SubscriptionEvent) have been moved to apps.subscriptions.models.

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
