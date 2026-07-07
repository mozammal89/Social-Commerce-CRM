"""
Signal handlers for the RBAC system.

This module is loaded by ``apps.permissions.apps.PermissionsConfig.ready()``
and is responsible for three things:

1. ``run_sync_permissions``  — called via ``post_migrate`` to keep the
   ``Resource`` and ``Permission`` tables in sync with the registry.

2. Cache invalidation  — when an RBAC row changes, bump the relevant
   version stamp so cached permission/feature sets are ignored.

3. Audit emission  — write ``AuditLog`` rows on RBAC mutations. The
   handler uses ``_pre_capture`` to stash the pre-state on the instance
   so post_save can compute ``before``/``after``.

Signal handlers must never raise — they wrap risky work in try/except so
that a misconfigured logging target cannot break a save.
"""

from __future__ import annotations

import datetime as _dt
import decimal as _decimal
import logging
import uuid as _uuid
from typing import Any

from django.core.management import call_command
from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.forms.models import model_to_dict

from .cache import (
    bump_store_plan_version,
    bump_user_version,
)
from .constants import (
    AUDIT_MEMBERSHIP_CREATE,
    AUDIT_MEMBERSHIP_DELETE,
    AUDIT_MEMBERSHIP_UPDATE,
    AUDIT_OVERRIDE_CREATE,
    AUDIT_OVERRIDE_DELETE,
    AUDIT_OVERRIDE_UPDATE,
    AUDIT_PLAN_CREATE,
    AUDIT_PLAN_UPDATE,
    AUDIT_ROLE_CREATE,
    AUDIT_ROLE_DELETE,
    AUDIT_ROLE_PERMISSION_CREATE,
    AUDIT_ROLE_PERMISSION_DELETE,
    AUDIT_ROLE_PERMISSION_UPDATE,
    AUDIT_ROLE_UPDATE,
    AUDIT_SUBSCRIPTION_CREATE,
    AUDIT_SUBSCRIPTION_UPDATE,
)
from .middleware import current_request_context
from .models import (
    AuditLog,
    Role,
    RolePermission,
    StoreMembership,
    UserPermissionOverride,
)
from apps.subscriptions.models import (
    Subscription,
    SubscriptionPlan,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# post_migrate: registry → DB sync
# ---------------------------------------------------------------------------
def run_sync_permissions(sender, **kwargs):
    """Run sync_permissions on every migrate. Idempotent."""
    try:
        call_command("sync_permissions", verbosity=0)
    except Exception:
        # Never let a sync failure break migrations.
        logger.exception("sync_permissions failed during post_migrate")


# ---------------------------------------------------------------------------
# Cache invalidation helpers
# ---------------------------------------------------------------------------
def _bump_user(user_id) -> None:
    if user_id:
        bump_user_version(user_id)


def _bump_users_for_role(role_id) -> None:
    if not role_id:
        return
    for uid in (
        StoreMembership.objects.filter(role_id=role_id)
        .values_list("user_id", flat=True)
        .distinct()
    ):
        _bump_user(uid)


def _bump_store_plan(store_id) -> None:
    if store_id:
        bump_store_plan_version(store_id)


# ---- RBAC change signals --------------------------------------------------

def _on_role_permission_change(sender, instance, **kwargs):
    role_id = instance.role_id
    transaction.on_commit(lambda: _bump_users_for_role(role_id))


def _on_membership_change(sender, instance, **kwargs):
    user_id = instance.user_id
    store_id = instance.store_id
    transaction.on_commit(lambda: _bump_user(user_id))
    transaction.on_commit(lambda: _bump_store_plan(store_id))


def _on_override_change(sender, instance, **kwargs):
    user_id = instance.user_id
    transaction.on_commit(lambda: _bump_user(user_id))


def _on_subscription_change(sender, instance, **kwargs):
    store_id = instance.store_id
    transaction.on_commit(lambda: _bump_store_plan(store_id))


def _on_plan_change(sender, instance, **kwargs):
    # Plan changes affect every store on that plan. Defer to post-commit
    # to avoid transaction issues when querying Subscription table.
    def bump_plan_stores():
        try:
            from apps.subscriptions.models import Subscription
            for sid in Subscription.objects.filter(plan=instance).values_list(
                "store_id", flat=True
            ):
                _bump_store_plan(sid)
        except Exception:
            logger.exception("Plan change bump failed")

    transaction.on_commit(bump_plan_stores)


# ---------------------------------------------------------------------------
# Audit emission
# ---------------------------------------------------------------------------
def _safe_model_to_dict(instance) -> dict[str, Any]:
    try:
        d = model_to_dict(instance)
    except Exception:
        d = {"id": str(getattr(instance, "pk", ""))}
    return _json_safe(_stringify_uuids(d))


def _stringify_uuids(d: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in d.items():
        if hasattr(v, "hex"):  # UUID instance
            out[k] = str(v)
        else:
            out[k] = v
    return out


def _json_safe(value: Any) -> Any:
    """Recursively coerce a value into something ``json.dumps`` can handle.

    ``model_to_dict`` returns raw ``datetime``/``date``/``Decimal``/``UUID``/
    ``bytes`` instances which the default ``json`` encoder cannot serialize.
    PostgreSQL's ``JSONField`` adapter calls ``json.dumps`` on the dict and
    raises ``TypeError: Object of type datetime is not JSON serializable``
    if any of those slip through. The model layer also uses
    ``DjangoJSONEncoder`` as a second line of defense, but we sanitize here
    too so the signal path never depends on a particular field encoder
    being configured.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, _dt.datetime):
        return value.isoformat()
    if isinstance(value, _dt.date):
        return value.isoformat()
    if isinstance(value, _dt.time):
        return value.isoformat()
    if isinstance(value, _dt.timedelta):
        return value.total_seconds()
    if isinstance(value, _decimal.Decimal):
        return str(value)
    if isinstance(value, _uuid.UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(v) for v in value]
    # Fallback: best-effort stringification so the audit row never crashes.
    try:
        return str(value)
    except Exception:
        return None


def _log(action: str, target_type: str, instance, before=None, after=None):
    """Write an AuditLog row from current request context.

    No-ops if there is no active request context (e.g. during seeders,
    management commands, or background jobs that haven't set one). This
    prevents audit logs from accumulating on automated operations.

    The store_id resolution prefers the instance's own FK when available,
    falling back to the contextvar. This prevents AuditLog rows from
    pointing at a Store that exists in some other test's DB when the
    contextvar leaks across test boundaries.
    """
    ctx = current_request_context()
    if ctx is None:
        return  # No user-initiated request; skip audit.

    instance_store_id = getattr(instance, "store_id", None)
    ctx_store_id = ctx.get("store_id")
    target_id = str(getattr(instance, "pk", ""))

    # Defer AuditLog creation to after the transaction commits.
    # This prevents transaction errors if the AuditLog creation fails.
    def create_audit_log():
        try:
            AuditLog.objects.create(
                actor=ctx.get("user"),
                store_id=instance_store_id if instance_store_id is not None else ctx_store_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                before=before,
                after=after,
                ip_address=ctx.get("ip"),
                user_agent=(ctx.get("ua") or "")[:512],
                request_id=ctx.get("request_id") or "",
            )
        except Exception:
            # Audit must never break the save.
            logger.exception("Failed to write AuditLog row for %s", action)

    # Use on_commit if we're in a transaction, otherwise create immediately
    if transaction.get_connection().in_atomic_block:
        transaction.on_commit(create_audit_log)
    else:
        create_audit_log()


def _pre_capture(sender, instance, **kwargs):
    """
    Stash pre-state on the instance so post_save can diff it.
    Only for instances that already have a PK (i.e. updates).
    """
    if not instance.pk:
        instance._pre_state = None
        return
    try:
        instance._pre_state = sender.objects.get(pk=instance.pk)
    except sender.DoesNotExist:
        instance._pre_state = None
    except Exception:
        instance._pre_state = None


def _before_dict(instance) -> dict | None:
    pre = getattr(instance, "_pre_state", None)
    if pre is None:
        return None
    return _safe_model_to_dict(pre)


# ---- Audit handlers per model --------------------------------------------

def _on_role_save(sender, instance, created, **kwargs):
    _log(
        AUDIT_ROLE_CREATE if created else AUDIT_ROLE_UPDATE,
        "Role",
        instance,
        before=None if created else _before_dict(instance),
        after=_safe_model_to_dict(instance),
    )


def _on_role_delete(sender, instance, **kwargs):
    _log(
        AUDIT_ROLE_DELETE,
        "Role",
        instance,
        before=_safe_model_to_dict(instance),
    )


def _on_rp_save(sender, instance, created, **kwargs):
    _log(
        AUDIT_ROLE_PERMISSION_CREATE if created else AUDIT_ROLE_PERMISSION_UPDATE,
        "RolePermission",
        instance,
        before=None if created else _before_dict(instance),
        after=_safe_model_to_dict(instance),
    )


def _on_rp_delete(sender, instance, **kwargs):
    _log(
        AUDIT_ROLE_PERMISSION_DELETE,
        "RolePermission",
        instance,
        before=_safe_model_to_dict(instance),
    )


def _on_mem_save(sender, instance, created, **kwargs):
    _log(
        AUDIT_MEMBERSHIP_CREATE if created else AUDIT_MEMBERSHIP_UPDATE,
        "StoreMembership",
        instance,
        before=None if created else _before_dict(instance),
        after=_safe_model_to_dict(instance),
    )


def _on_mem_delete(sender, instance, **kwargs):
    _log(
        AUDIT_MEMBERSHIP_DELETE,
        "StoreMembership",
        instance,
        before=_safe_model_to_dict(instance),
    )


def _on_override_save(sender, instance, created, **kwargs):
    _log(
        AUDIT_OVERRIDE_CREATE if created else AUDIT_OVERRIDE_UPDATE,
        "UserPermissionOverride",
        instance,
        before=None if created else _before_dict(instance),
        after=_safe_model_to_dict(instance),
    )


def _on_override_delete(sender, instance, **kwargs):
    _log(
        AUDIT_OVERRIDE_DELETE,
        "UserPermissionOverride",
        instance,
        before=_safe_model_to_dict(instance),
    )


def _on_subscription_save(sender, instance, created, **kwargs):
    _log(
        AUDIT_SUBSCRIPTION_CREATE if created else AUDIT_SUBSCRIPTION_UPDATE,
        "Subscription",
        instance,
        before=None if created else _before_dict(instance),
        after=_safe_model_to_dict(instance),
    )


def _on_plan_save(sender, instance, created, **kwargs):
    _log(
        AUDIT_PLAN_CREATE if created else AUDIT_PLAN_UPDATE,
        "SubscriptionPlan",
        instance,
        before=None if created else _before_dict(instance),
        after=_safe_model_to_dict(instance),
    )


# ---------------------------------------------------------------------------
# Connect/disconnect
# ---------------------------------------------------------------------------
def connect_cache_signals() -> None:
    """Wire cache invalidation signals. Idempotent."""
    post_save.connect(_on_role_permission_change, sender=RolePermission, dispatch_uid="rbac.rp.save")
    post_delete.connect(_on_role_permission_change, sender=RolePermission, dispatch_uid="rbac.rp.delete")
    post_save.connect(_on_membership_change, sender=StoreMembership, dispatch_uid="rbac.mem.save")
    post_delete.connect(_on_membership_change, sender=StoreMembership, dispatch_uid="rbac.mem.delete")
    post_save.connect(_on_override_change, sender=UserPermissionOverride, dispatch_uid="rbac.ov.save")
    post_delete.connect(_on_override_change, sender=UserPermissionOverride, dispatch_uid="rbac.ov.delete")
    post_save.connect(_on_subscription_change, sender=Subscription, dispatch_uid="rbac.sub.save")
    post_save.connect(_on_plan_change, sender=SubscriptionPlan, dispatch_uid="rbac.plan.save")


def connect_audit_signals() -> None:
    """Wire audit signals. Idempotent."""
    pre_save.connect(_pre_capture, sender=Role, dispatch_uid="rbac.audit.role.pre")
    post_save.connect(_on_role_save, sender=Role, dispatch_uid="rbac.audit.role.save")
    post_delete.connect(_on_role_delete, sender=Role, dispatch_uid="rbac.audit.role.delete")

    pre_save.connect(_pre_capture, sender=RolePermission, dispatch_uid="rbac.audit.rp.pre")
    post_save.connect(_on_rp_save, sender=RolePermission, dispatch_uid="rbac.audit.rp.save")
    post_delete.connect(_on_rp_delete, sender=RolePermission, dispatch_uid="rbac.audit.rp.delete")

    pre_save.connect(_pre_capture, sender=StoreMembership, dispatch_uid="rbac.audit.mem.pre")
    post_save.connect(_on_mem_save, sender=StoreMembership, dispatch_uid="rbac.audit.mem.save")
    post_delete.connect(_on_mem_delete, sender=StoreMembership, dispatch_uid="rbac.audit.mem.delete")

    pre_save.connect(_pre_capture, sender=UserPermissionOverride, dispatch_uid="rbac.audit.ov.pre")
    post_save.connect(_on_override_save, sender=UserPermissionOverride, dispatch_uid="rbac.audit.ov.save")
    post_delete.connect(_on_override_delete, sender=UserPermissionOverride, dispatch_uid="rbac.audit.ov.delete")

    pre_save.connect(_pre_capture, sender=Subscription, dispatch_uid="rbac.audit.sub.pre")
    post_save.connect(_on_subscription_save, sender=Subscription, dispatch_uid="rbac.audit.sub.save")

    pre_save.connect(_pre_capture, sender=SubscriptionPlan, dispatch_uid="rbac.audit.plan.pre")
    post_save.connect(_on_plan_save, sender=SubscriptionPlan, dispatch_uid="rbac.audit.plan.save")


# Auto-connect on import.
connect_cache_signals()
connect_audit_signals()