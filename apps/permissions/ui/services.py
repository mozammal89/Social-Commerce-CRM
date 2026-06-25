"""
Business-logic services for the role/permission management UI.

All mutations here:
  * Validate that the actor has authority to perform the action.
  * Wrap database writes in ``transaction.atomic()``.
  * Emit an ``AuditLog`` entry capturing before/after state.

Views must never call the ORM directly for these operations — they
should call the corresponding function from this module.
"""

from __future__ import annotations

import logging
from typing import Iterable

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from apps.permissions.constants import MODIFIER_GRANT
from apps.permissions.models import (
    AuditLog,
    Permission,
    Role,
    RolePermission,
    StoreMembership,
    UserPermissionOverride,
)
from apps.permissions.services import user_has_permission
from apps.stores.models import Store

from .constants import (
    PERM_MEMBERS_MANAGE,
    PERM_OVERRIDE_GRANT,
    PERM_ROLES_MANAGE,
)

logger = logging.getLogger(__name__)
User = get_user_model()


# ---------------------------------------------------------------------------
# Audit logging helper
# ---------------------------------------------------------------------------
def _emit_audit_log(
    *,
    actor,
    store: Store | None,
    action: str,
    target_type: str,
    target_id: str,
    before: dict | None = None,
    after: dict | None = None,
    request=None,
) -> None:
    """Write a single AuditLog entry."""
    ip = None
    ua = ""
    rid = ""
    if request is not None:
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        ip = xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR")
        ua = request.META.get("HTTP_USER_AGENT", "")[:512]
        rid = request.META.get("HTTP_X_REQUEST_ID", "")

    AuditLog.objects.create(
        actor=actor if (actor and getattr(actor, "is_authenticated", False)) else None,
        store=store,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        before=before,
        after=after,
        ip_address=ip,
        user_agent=ua,
        request_id=rid,
    )


def _serialize_role(role: Role) -> dict:
    return {
        "id": str(role.id),
        "name": role.name,
        "slug": role.slug,
        "level": role.level,
        "is_system": role.is_system,
        "is_active": role.is_active,
        "store_id": str(role.store_id) if role.store_id else None,
        "description": role.description,
        "inherits_from_id": str(role.inherits_from_id) if role.inherits_from_id else None,
    }


# ---------------------------------------------------------------------------
# Role CRUD
# ---------------------------------------------------------------------------
def create_role(
    *,
    actor,
    store: Store | None,
    name: str,
    description: str = "",
    is_system: bool = False,
    level: int = 0,
    inherits_from: Role | None = None,
    request=None,
) -> Role:
    """
    Create a new role.

    - If ``store`` is None, a system role is created (superuser only).
    - Otherwise a custom store-scoped role is created.
    """
    _require_role_manage(actor, store)

    if is_system and not actor.is_superuser:
        raise PermissionError("Only superusers can create system roles.")

    slug = slugify(name)
    if not slug:
        raise ValueError("Name must contain at least one alphanumeric character.")

    with transaction.atomic():
        role = Role.objects.create(
            name=name,
            slug=slug,
            description=description,
            store=store,
            is_system=is_system,
            level=level,
            inherits_from=inherits_from,
        )
        _emit_audit_log(
            actor=actor,
            store=store,
            action="role.create",
            target_type="role",
            target_id=str(role.id),
            after=_serialize_role(role),
            request=request,
        )

    logger.info("Role created: %s (store=%s, system=%s)", role.id, store, is_system)
    return role


def update_role(
    *,
    actor,
    role: Role,
    name: str | None = None,
    description: str | None = None,
    level: int | None = None,
    is_active: bool | None = None,
    request=None,
) -> Role:
    """Update editable fields of a role."""
    _require_role_manage(actor, role.store)

    if role.is_system and not actor.is_superuser:
        raise PermissionError("System roles cannot be modified by non-superusers.")

    before = _serialize_role(role)
    with transaction.atomic():
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description
        if level is not None and not role.is_system:
            role.level = level
        if is_active is not None and not role.is_system:
            role.is_active = is_active
        role.save()

        _emit_audit_log(
            actor=actor,
            store=role.store,
            action="role.update",
            target_type="role",
            target_id=str(role.id),
            before=before,
            after=_serialize_role(role),
            request=request,
        )

    return role


def delete_role(*, actor, role: Role, request=None) -> None:
    """
    Delete (or deactivate) a role.

    System roles cannot be deleted; they are deactivated instead.
    Roles with active memberships are deactivated, not deleted.
    """
    _require_role_manage(actor, role.store)

    if role.is_system and not actor.is_superuser:
        raise PermissionError("System roles cannot be deleted.")

    active_members = StoreMembership.objects.filter(role=role, is_active=True).exists()

    with transaction.atomic():
        before = _serialize_role(role)
        if role.is_system or active_members:
            # Soft-delete: deactivate
            role.is_active = False
            role.save(update_fields=["is_active", "updated_at"])
            _emit_audit_log(
                actor=actor,
                store=role.store,
                action="role.deactivate",
                target_type="role",
                target_id=str(role.id),
                before=before,
                after=_serialize_role(role),
                request=request,
            )
        else:
            role.delete()
            _emit_audit_log(
                actor=actor,
                store=role.store,
                action="role.delete",
                target_type="role",
                target_id=str(role.id),
                before=before,
                request=request,
            )


def clone_role(*, actor, role: Role, new_name: str, request=None) -> Role:
    """Clone an existing role, copying all RolePermission rows."""
    _require_role_manage(actor, role.store)

    slug = slugify(new_name)
    if not slug:
        raise ValueError("Name must contain at least one alphanumeric character.")

    with transaction.atomic():
        new_role = Role.objects.create(
            name=new_name,
            slug=slug,
            description=role.description,
            store=role.store,
            is_system=False,
            level=role.level,
            inherits_from=role,
        )

        source_perms = list(
            RolePermission.objects.filter(role=role).values(
                "permission_id",
                "modifier",
            )
        )
        RolePermission.objects.bulk_create(
            [
                RolePermission(
                    role=new_role,
                    permission_id=row["permission_id"],
                    modifier=row["modifier"],
                )
                for row in source_perms
            ]
        )

        _emit_audit_log(
            actor=actor,
            store=new_role.store,
            action="role.clone",
            target_type="role",
            target_id=str(new_role.id),
            after={
                **_serialize_role(new_role),
                "cloned_from_id": str(role.id),
                "permission_count": len(source_perms),
            },
            request=request,
        )

    return new_role


# ---------------------------------------------------------------------------
# Role <-> Permission bindings
# ---------------------------------------------------------------------------
def set_role_permissions(
    *,
    actor,
    role: Role,
    permission_ids: Iterable[str],
    modifier: str = MODIFIER_GRANT,
    request=None,
) -> int:
    """
    Replace the permission set on a role with ``permission_ids``.

    Returns the number of bindings written.
    """
    _require_role_manage(actor, role.store)

    if role.is_system and not actor.is_superuser:
        raise PermissionError("Cannot modify system role permissions.")

    perm_ids = list({str(p) for p in permission_ids})
    valid_ids = set(Permission.objects.filter(id__in=perm_ids).values_list("id", flat=True))

    with transaction.atomic():
        before_perms = set(
            RolePermission.objects.filter(role=role).values_list("permission_id", flat=True)
        )

        RolePermission.objects.filter(role=role).delete()

        perms = Permission.objects.filter(id__in=valid_ids)
        new_bindings = [RolePermission(role=role, permission=p, modifier=modifier) for p in perms]
        RolePermission.objects.bulk_create(new_bindings)

        after_perms = set(
            RolePermission.objects.filter(role=role).values_list("permission_id", flat=True)
        )

        _emit_audit_log(
            actor=actor,
            store=role.store,
            action="role.permissions.replace",
            target_type="role",
            target_id=str(role.id),
            before={
                "permission_ids": sorted(str(p) for p in before_perms),
                "modifier": modifier,
            },
            after={
                "permission_ids": sorted(str(p) for p in after_perms),
                "modifier": modifier,
            },
            request=request,
        )

    return len(new_bindings)


def toggle_role_permission(
    *,
    actor,
    role: Role,
    permission_id: str,
    request=None,
) -> bool:
    """
    Toggle a single permission on/off for a role.

    Returns True if the permission is now granted, False if removed.
    """
    _require_role_manage(actor, role.store)
    if role.is_system and not actor.is_superuser:
        raise PermissionError("Cannot modify system role permissions.")

    with transaction.atomic():
        try:
            binding = RolePermission.objects.get(role=role, permission_id=permission_id)
            binding.delete()
            now_granted = False
        except RolePermission.DoesNotExist:
            RolePermission.objects.create(
                role=role,
                permission_id=permission_id,
                modifier=MODIFIER_GRANT,
            )
            now_granted = True

        _emit_audit_log(
            actor=actor,
            store=role.store,
            action="role.permission.toggle",
            target_type="role",
            target_id=str(role.id),
            after={"permission_id": str(permission_id), "granted": now_granted},
            request=request,
        )

    return now_granted


# ---------------------------------------------------------------------------
# Store membership
# ---------------------------------------------------------------------------
def add_member(
    *,
    actor,
    store: Store,
    user,
    role: Role,
    expires_at=None,
    request=None,
    check_seats=True,
) -> StoreMembership:
    """Add a user to a store with a given role (idempotent on user+store+role)."""
    _require_members_manage(actor, store)

    if role.store_id is not None and role.store_id != store.id:
        raise ValueError("Role does not belong to this store.")

    # Prevent self-invitation
    if actor == user:
        raise PermissionError(
            "You cannot add yourself as a member. You are already the store owner."
        )

    # Check if user is already a member (including inactive)
    existing_membership = StoreMembership.objects.filter(user=user, store=store).first()

    if existing_membership:
        # If reactivating an existing membership, check if they're a store owner
        # Store owners don't consume seats, so no seat check needed
        if not existing_membership.is_active and check_seats:
            try:
                from apps.permissions.models import Role as RoleModel

                # Check if this is a store owner role
                is_owner_role = role.slug == "store-owner" or (
                    role.store_id is None and role.slug == "store-owner"
                )

                if not is_owner_role:
                    # For non-owners, check seat availability when reactivating
                    from apps.subscriptions.services import check_plan_limits
                    from apps.subscriptions.exceptions import PlanLimitExceeded

                    limits_info = check_plan_limits(store)
                    current_usage = limits_info.get("usage", {}).get("users", 0)
                    max_users = limits_info.get("limits", {}).get("max_users", 0)

                    if current_usage >= max_users:
                        raise PlanLimitExceeded("max_users", current_usage + 1, max_users)
            except PlanLimitExceeded:
                raise
            except Exception:
                # If seat check fails, log but continue (better to allow than block)
                logger.warning("Failed to check seat limits during membership reactivation")

    # If creating a new membership, check seat availability
    if not existing_membership and check_seats:
        try:
            from apps.subscriptions.services import check_plan_limits
            from apps.subscriptions.exceptions import PlanLimitExceeded

            # Check if this is a store owner role
            is_owner_role = role.slug == "store-owner" or (
                role.store_id is None and role.slug == "store-owner"
            )

            # Store owners don't consume seats
            if not is_owner_role:
                limits_info = check_plan_limits(store)
                current_usage = limits_info.get("usage", {}).get("users", 0)
                max_users = limits_info.get("limits", {}).get("max_users", 0)

                logger.info(
                    f"Seat check for adding user {user.id} to store {store.id}: "
                    f"current={current_usage}, max={max_users}, role={role.slug}"
                )

                if current_usage >= max_users:
                    raise PlanLimitExceeded("max_users", current_usage + 1, max_users)
        except PlanLimitExceeded:
            raise
        except Exception:
            # If seat check fails, log but continue (better to allow than block)
            logger.warning("Failed to check seat limits during membership creation")

    with transaction.atomic():
        membership, created = StoreMembership.objects.get_or_create(
            user=user,
            store=store,
            role=role,
            defaults={
                "is_active": True,
                "invited_by": actor if actor.is_authenticated else None,
                "expires_at": expires_at,
            },
        )
        if not created and not membership.is_active:
            membership.is_active = True
            membership.invited_by = actor if actor.is_authenticated else None
            membership.expires_at = expires_at
            membership.save()

        _emit_audit_log(
            actor=actor,
            store=store,
            action="member.add" if created else "member.reactivate",
            target_type="store_membership",
            target_id=str(membership.id),
            after={
                "user_id": str(user.id),
                "role_id": str(role.id),
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
            request=request,
        )

        if created:
            logger.info(
                f"Created new membership: user {user.id}, store {store.id}, "
                f"role {role.id} ({role.slug})"
            )

    return membership


def change_member_role(
    *,
    actor,
    membership: StoreMembership,
    new_role: Role,
    request=None,
) -> StoreMembership:
    """Change a member's role within the same store."""
    _require_members_manage(actor, membership.store)

    if new_role.store_id is not None and new_role.store_id != membership.store_id:
        raise ValueError("New role does not belong to the same store.")

    with transaction.atomic():
        before = {
            "role_id": str(membership.role_id),
            "is_active": membership.is_active,
        }
        membership.role = new_role
        membership.save(update_fields=["role", "updated_at"])
        _emit_audit_log(
            actor=actor,
            store=membership.store,
            action="member.role.change",
            target_type="store_membership",
            target_id=str(membership.id),
            before=before,
            after={
                "role_id": str(new_role.id),
                "is_active": membership.is_active,
            },
            request=request,
        )
    return membership


def deactivate_member(
    *,
    actor,
    membership: StoreMembership,
    request=None,
) -> StoreMembership:
    """Deactivate a membership (soft delete)."""
    _require_members_manage(actor, membership.store)

    with transaction.atomic():
        before = {"is_active": membership.is_active}
        membership.is_active = False
        membership.save(update_fields=["is_active", "updated_at"])
        _emit_audit_log(
            actor=actor,
            store=membership.store,
            action="member.deactivate",
            target_type="store_membership",
            target_id=str(membership.id),
            before=before,
            after={"is_active": False},
            request=request,
        )
    return membership


def reactivate_member(
    *,
    actor,
    membership: StoreMembership,
    request=None,
) -> StoreMembership:
    """Reactivate a previously deactivated membership."""
    _require_members_manage(actor, membership.store)

    with transaction.atomic():
        before = {"is_active": membership.is_active}
        membership.is_active = True
        membership.save(update_fields=["is_active", "updated_at"])
        _emit_audit_log(
            actor=actor,
            store=membership.store,
            action="member.reactivate",
            target_type="store_membership",
            target_id=str(membership.id),
            before=before,
            after={"is_active": True},
            request=request,
        )
    return membership


# ---------------------------------------------------------------------------
# User-level permission overrides
# ---------------------------------------------------------------------------
def set_user_override(
    *,
    actor,
    target_user,
    store: Store | None,
    permission: Permission,
    is_granted: bool,
    reason: str = "",
    expires_at=None,
    request=None,
) -> UserPermissionOverride:
    """
    Create or update a per-user override for a permission.

    Superusers can set overrides anywhere. Store admins can only set
    overrides within stores they administer.
    """
    if not actor.is_superuser:
        if store is None:
            raise PermissionError("Only superusers can set cross-store overrides.")
        if not user_has_permission(actor, store, PERM_OVERRIDE_GRANT):
            raise PermissionError("You don't have permission to grant overrides in this store.")

    with transaction.atomic():
        override, created = UserPermissionOverride.objects.update_or_create(
            user=target_user,
            store=store,
            permission=permission,
            defaults={
                "is_granted": is_granted,
                "reason": reason,
                "granted_by": actor if actor.is_authenticated else None,
                "expires_at": expires_at,
            },
        )
        _emit_audit_log(
            actor=actor,
            store=store,
            action="override.set" if created else "override.update",
            target_type="user_permission_override",
            target_id=str(override.id),
            after={
                "user_id": str(target_user.id),
                "permission_id": str(permission.id),
                "is_granted": is_granted,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
            request=request,
        )
    return override


def clear_user_override(
    *,
    actor,
    override: UserPermissionOverride,
    request=None,
) -> None:
    """Remove a per-user override."""
    if not actor.is_superuser and override.store_id:
        if not user_has_permission(actor, override.store, PERM_OVERRIDE_GRANT):
            raise PermissionError("Cannot clear override in this store.")

    with transaction.atomic():
        before = {
            "user_id": str(override.user_id),
            "permission_id": str(override.permission_id),
            "store_id": str(override.store_id) if override.store_id else None,
            "is_granted": override.is_granted,
        }
        override.delete()
        _emit_audit_log(
            actor=actor,
            store=override.store,
            action="override.clear",
            target_type="user_permission_override",
            target_id=str(override.id),
            before=before,
            request=request,
        )


# ---------------------------------------------------------------------------
# Internal authorization helpers
# ---------------------------------------------------------------------------
def _require_role_manage(actor, store: Store | None) -> None:
    if not actor or not getattr(actor, "is_authenticated", False):
        raise PermissionError("Authentication required.")
    if actor.is_superuser:
        return
    if store is None:
        raise PermissionError("Only superusers may manage system roles.")
    if not user_has_permission(actor, store, PERM_ROLES_MANAGE):
        raise PermissionError("You don't have permission to manage roles in this store.")


def _require_members_manage(actor, store: Store | None) -> None:
    if not actor or not getattr(actor, "is_authenticated", False):
        raise PermissionError("Authentication required.")
    if actor.is_superuser:
        return
    if store is None:
        raise PermissionError("Members must belong to a store.")
    if not user_has_permission(actor, store, PERM_MEMBERS_MANAGE):
        raise PermissionError("You don't have permission to manage members in this store.")
