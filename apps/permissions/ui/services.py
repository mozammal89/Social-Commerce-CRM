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

from apps.permissions.constants import MODIFIER_GRANT, ROLE_STORE_OWNER
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

    Defense-in-depth: even if a future caller skips the view-level
    ``SubscriptionRequiredMixin``, store-scoped role creation requires
    an active subscription. A canceled user must not be able to stage
    a role hierarchy on a tenant that doesn't correspond to any plan
    they're paying for.
    """
    _require_role_manage(actor, store)

    # Active-subscription guard for store-scoped roles. Skipped for
    # system roles (``store is None``) since those are platform-wide
    # and only superusers can create them. Checked *before* the
    # is_system superuser guard above so that a canceled store owner
    # always gets the clearer "subscription" error rather than the
    # RBAC one.
    if store is not None and not getattr(actor, "is_superuser", False):
        from apps.permissions.services import store_has_active_subscription

        if not store_has_active_subscription(store):
            raise PermissionError(
                "Cannot create roles while your subscription is inactive. "
                "Renew or pick a new plan to continue."
            )

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

    # Active-subscription guard for store-scoped roles — see
    # ``create_role`` for rationale. Skipped for system roles
    # (``role.store is None``) which only superusers can touch.
    if role.store is not None and not getattr(actor, "is_superuser", False):
        from apps.permissions.services import store_has_active_subscription

        if not store_has_active_subscription(role.store):
            raise PermissionError(
                "Cannot edit roles while your subscription is inactive. "
                "Renew or pick a new plan to continue."
            )

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

    # Active-subscription guard — see ``create_role`` for rationale.
    if role.store is not None and not getattr(actor, "is_superuser", False):
        from apps.permissions.services import store_has_active_subscription

        if not store_has_active_subscription(role.store):
            raise PermissionError(
                "Cannot delete roles while your subscription is inactive. "
                "Renew or pick a new plan to continue."
            )

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

    # Active-subscription guard. The view-level mixin and the
    # ``invite_member`` function-view both already enforce this, but a
    # missing subscription means ``enforce_reserved_seat_cap`` (called
    # below) silently fails open — the seat-cap falls back to allowing
    # the write because ``check_plan_limits`` returns empty usage for
    # canceled subs. That bypass would let a canceled user pre-invite
    # hundreds of members, then re-subscribe to Starter (max_users=3)
    # and evade the cap. Defense in depth: reject the write here too.
    if not getattr(actor, "is_superuser", False):
        from apps.permissions.services import store_has_active_subscription

        if not store_has_active_subscription(store):
            raise PermissionError(
                "Cannot add members while your subscription is inactive. "
                "Renew or pick a new plan to continue."
            )

    if role.store_id is not None and role.store_id != store.id:
        raise ValueError("Role does not belong to this store.")

    # Prevent self-invitation
    if actor == user:
        raise PermissionError(
            "You cannot add yourself as a member. You are already the store owner."
        )

    # Check if user is already a member (including inactive)
    existing_membership = StoreMembership.objects.filter(user=user, store=store).first()

    if check_seats and not _is_store_owner_role(role):
        # Single helper closes the deactivate/reactivate bypass: it
        # uses ``reserved_users`` (active + inactive), not the active
        # count, so a deactivated member still occupies its seat.
        #
        # ``block_when_equal`` distinguishes the two write paths:
        # * ``add`` (new row) — must enforce ``reserved >= max`` because
        #   the new row would push reserved over the cap.
        # * ``reactivate`` (existing row) — the row is already counted
        #   in reserved, so equality is safe; only block when the cap
        #   has already been breached (``reserved > max``).
        from apps.subscriptions.services import enforce_reserved_seat_cap
        from apps.subscriptions.exceptions import PlanLimitExceeded

        if existing_membership and not existing_membership.is_active:
            action, block_when_equal = "reactivate", False
        elif existing_membership:
            # Idempotent: membership already active, no seat change.
            action = None
        else:
            action, block_when_equal = "add", True

        if action is not None:
            try:
                enforce_reserved_seat_cap(
                    store, action=action, block_when_equal=block_when_equal,
                )
            except PlanLimitExceeded:
                raise
            except Exception:
                # Fail open on infra errors (DB hiccup, cache miss).
                # ``PlanLimitExceeded`` propagates above; only other
                # exceptions are swallowed here.
                logger.warning(
                    "Seat-cap check failed for store=%s user=%s; "
                    "failing open",
                    store.id, getattr(user, "id", None),
                    exc_info=True,
                )
            except Exception:
                # Fail open on unexpected errors (DB hiccup, cache
                # miss, etc.) — better to allow a write than block
                # legitimate operations during infra incidents.
                logger.warning(
                    "Seat-cap check failed for store=%s user=%s; "
                    "failing open",
                    store.id, getattr(user, "id", None),
                    exc_info=True,
                )

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
    """Reactivate a previously deactivated membership.

    Enforces the seat-cap using ``reserved_users`` semantics: a
    deactivated row still occupies its seat, so reactivation can only
    succeed if there is a free seat. Without this check the team UI
    can be abused to bypass the limit (deactivate A → invite B →
    reactivate A → invite C → ... indefinitely).
    """
    _require_members_manage(actor, membership.store)

    # Active-subscription guard — see ``add_member`` for rationale.
    if not getattr(actor, "is_superuser", False):
        from apps.permissions.services import store_has_active_subscription

        if not store_has_active_subscription(membership.store):
            raise PermissionError(
                "Cannot reactivate members while your subscription is "
                "inactive. Renew or pick a new plan to continue."
            )

    # Idempotent: reactivating an already-active membership is a no-op.
    if membership.is_active:
        return membership

    # Skip the seat check for store-owner roles — they don't consume
    # seats (same exemption as ``add_member``).
    if not _is_store_owner_role(membership.role):
        # Reactivation doesn't change ``reserved_users`` (the row is
        # already counted), so we block only when reserved > max
        # (``block_when_equal=False``). The add/write-path enforces
        # ``reserved >= max`` via the same helper.
        from apps.subscriptions.services import enforce_reserved_seat_cap

        enforce_reserved_seat_cap(
            membership.store, action="reactivate", block_when_equal=False,
        )

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

    # Active-subscription guard for store-scoped overrides — see
    # ``create_role`` for rationale.
    if store is not None and not getattr(actor, "is_superuser", False):
        from apps.permissions.services import store_has_active_subscription

        if not store_has_active_subscription(store):
            raise PermissionError(
                "Cannot modify user overrides while your subscription is "
                "inactive. Renew or pick a new plan to continue."
            )

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


def set_user_overrides_bulk(
    *,
    actor,
    target_user,
    store: Store | None,
    permissions: Iterable[Permission],
    is_granted: bool,
    reason: str = "",
    expires_at=None,
    request=None,
) -> list[UserPermissionOverride]:
    """
    Create or update per-user overrides for multiple permissions.

    Superusers can set overrides anywhere. Store admins can only set
    overrides within stores they administer.

    Returns a list of created/updated overrides.
    """
    if not actor.is_superuser:
        if store is None:
            raise PermissionError("Only superusers can set cross-store overrides.")
        if not user_has_permission(actor, store, PERM_OVERRIDE_GRANT):
            raise PermissionError("You don't have permission to grant overrides in this store.")

    overrides = []
    with transaction.atomic():
        for permission in permissions:
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
            overrides.append(override)
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
    return overrides


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

    # Active-subscription guard — see ``set_user_override`` for
    # rationale.
    if override.store_id and not getattr(actor, "is_superuser", False):
        from apps.permissions.services import store_has_active_subscription

        if not store_has_active_subscription(override.store):
            raise PermissionError(
                "Cannot clear user overrides while your subscription is "
                "inactive. Renew or pick a new plan to continue."
            )

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


def _is_store_owner_role(role: Role) -> bool:
    """True if the role is the system store-owner role.

    Store owners don't consume seats; the seat-cap check skips them.
    """
    return role.slug == ROLE_STORE_OWNER
