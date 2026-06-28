"""
Public template-tag module for the role/permission UI.

Load with ``{% load rp_ui %}``.
"""

from django import template
import json

from ..context_processors import (
    role_permission_breadcrumbs,
    role_permission_sidebar_extra,
)

register = template.Library()


@register.simple_tag(takes_context=True)
def rp_breadcrumbs(context):
    """Render the role/permission breadcrumb list as HTML.

    Returns an empty string when the current page is not part of the
    role/permission UI.
    """
    request = context.get("request")
    if request is None:
        return ""
    crumbs = role_permission_breadcrumbs(request).get("rp_breadcrumbs", [])
    if not crumbs:
        return ""

    parts = ['<nav aria-label="breadcrumb"><ol class="breadcrumb mb-4">']
    home_url = crumbs[0]["url"] if crumbs[0].get("url") else "#"
    parts.append(
        '<li class="breadcrumb-item"><a href="{}"><i class="bi bi-house"></i> Home</a></li>'.format(
            home_url
        )
    )
    for crumb in crumbs[1:]:
        if crumb.get("url"):
            parts.append(
                '<li class="breadcrumb-item"><a href="{}">{}</a></li>'.format(
                    crumb["url"],
                    crumb["title"],
                )
            )
        else:
            parts.append(
                '<li class="breadcrumb-item active" aria-current="page">{}</li>'.format(
                    crumb["title"]
                )
            )
    parts.append("</ol></nav>")
    return "".join(parts)


@register.simple_tag(takes_context=True)
def rp_sidebar_active(context, url_name):
    """Return ``"active"`` if the current URL name matches."""
    request = context.get("request")
    match = getattr(request, "resolver_match", None) if request else None
    if not match:
        return ""
    if match.url_name == url_name and match.app_name == "role_permission":
        return "active"
    return ""


@register.filter
def format_audit_metadata(metadata, action=None):
    """Format audit log metadata in a user-friendly way.

    Args:
        metadata: Dictionary containing audit log metadata
        action: The audit action type (e.g., "member.invited", "role.create")

    Returns:
        User-friendly formatted string describing the metadata
    """
    if not metadata:
        return ""

    # First, resolve all UUIDs in the metadata to actual names
    resolved_metadata = _resolve_all_uuids(metadata)

    # Extract common fields from the resolved metadata
    user = resolved_metadata.get(
        "user", resolved_metadata.get("user_id", resolved_metadata.get("user_email", ""))
    )
    role = resolved_metadata.get(
        "role", resolved_metadata.get("role_name", resolved_metadata.get("role_id", ""))
    )
    permission = resolved_metadata.get(
        "permission",
        resolved_metadata.get("permission_name", resolved_metadata.get("permission_code", "")),
    )
    expires_at = resolved_metadata.get("expires_at")
    store = resolved_metadata.get("store", resolved_metadata.get("store_name", ""))

    # Format based on action type
    if action:
        # Member management actions
        if "invite" in action:
            description = f"Invited: {user}"
            if role:
                description += f" with role '{role}'"
            if expires_at:
                description += f", expires: {expires_at}"
            return description

        elif "reactivate" in action or "activate" in action:
            description = f"Reactivated: {user}"
            if role:
                description += f", now has role '{role}'"
            return description

        elif "deactivate" in action:
            description = f"Deactivated: {user}"
            previous_role = resolved_metadata.get("previous_role")
            if previous_role:
                description += f" (was '{previous_role}')"
            return description

        elif "remove" in action or "delete" in action:
            description = f"Removed: {user}"
            removed_role = resolved_metadata.get("removed_role", role)
            if removed_role:
                description += f" (was '{removed_role}')"
            return description

        elif "change" in action or "update" in action:
            if "role" in action or "role" in resolved_metadata.keys():
                new_role = resolved_metadata.get("new_role", resolved_metadata.get("role", ""))
                description = f"Changed role for: {user}"
                if new_role:
                    description += f" to '{new_role}'"
                return description
            elif "permission" in action:
                description = f"Modified permission override"
                if permission:
                    description += f": {permission}"
                return description

        # Role management actions
        elif "create" in action:
            if "role" in action.lower() or "Role" in resolved_metadata:
                role_name = resolved_metadata.get("name", resolved_metadata.get("role_name", ""))
                level = resolved_metadata.get("level", resolved_metadata.get("role_level", ""))
                inherits_from = resolved_metadata.get(
                    "inherits_from", resolved_metadata.get("inherits_from_name", "")
                )

                description = f"Created role: '{role_name}'"
                if level:
                    level_names = {0: "Owner", 1: "Admin", 2: "Manager", 3: "Staff", 4: "Viewer"}
                    level_name = level_names.get(level, f"Level {level}")
                    description += f" ({level_name})"
                if inherits_from:
                    description += f", inherits from '{inherits_from}'"
                return description

        elif "update" in action:
            if "role" in action.lower():
                role_name = resolved_metadata.get("name", resolved_metadata.get("role_name", ""))
                description = f"Updated role: '{role_name}'"
                return description

        elif "delete" in action and "role" in action.lower():
            role_name = resolved_metadata.get("name", resolved_metadata.get("role_name", role))
            return f"Deleted role: '{role_name}'"

        elif "clone" in action:
            original_role = resolved_metadata.get(
                "original_role", resolved_metadata.get("role", "")
            )
            new_name = resolved_metadata.get("new_name", resolved_metadata.get("role_name", ""))
            description = f"Cloned role '{original_role}' as '{new_name}'"
            return description

        # Permission management actions
        elif "toggle" in action:
            permission_name = resolved_metadata.get("permission_name", permission)
            granted = resolved_metadata.get("granted", resolved_metadata.get("is_granted", ""))
            granted_str = "Granted" if granted else "Revoked"
            return f"{granted_str} permission: '{permission_name}'"

        # Override actions
        elif "override" in action:
            target_user = resolved_metadata.get("target_user", resolved_metadata.get("user", ""))
            perm = resolved_metadata.get("permission", resolved_metadata.get("permission_name", ""))
            granted = resolved_metadata.get("granted", resolved_metadata.get("is_granted", ""))
            granted_str = "Grant" if granted else "Deny"
            reason = resolved_metadata.get("reason", "")

            description = f"{granted_str} permission '{perm}'"
            if target_user:
                description += f" to user: {target_user}"
            if reason:
                description += f" (Reason: {reason})"
            return description

    # Generic fallback formatting for common patterns
    parts = []
    if user:
        parts.append(f"User: {user}")
    if role:
        parts.append(f"Role: {role}")
    if permission:
        parts.append(f"Permission: {permission}")
    if store:
        parts.append(f"Store: {store}")
    if expires_at:
        parts.append(f"Expires: {expires_at}")

    if parts:
        return ", ".join(parts)

    # If no specific formatting, return a clean JSON-like string with resolved names
    try:
        if isinstance(resolved_metadata, dict):
            # Clean up common fields to make it more readable
            clean_metadata = {}
            for key, value in resolved_metadata.items():
                # Skip internal fields
                if key.startswith("_"):
                    continue
                # Format values
                if value and value != "":  # Skip empty values
                    clean_metadata[key] = value

            if clean_metadata:
                return ", ".join(f"{k}: {v}" for k, v in clean_metadata.items())
    except:
        pass

    return str(resolved_metadata) if resolved_metadata else ""


def _resolve_all_uuids(data, current_store=None):
    """Recursively resolve all UUIDs in metadata to actual names.

    Args:
        data: The metadata dictionary to resolve
        current_store: Optional store context for better resolution

    Returns:
        Dictionary with UUIDs replaced by actual names
    """
    if not data or not isinstance(data, dict):
        return data

    # Import models here to avoid module-level import issues
    from apps.accounts.models import User
    from apps.permissions.models import Role, Permission
    from apps.stores.models import Store

    resolved = {}

    for key, value in data.items():
        # Skip internal fields
        if key.startswith("_"):
            continue

        # Handle UUID resolution for specific fields
        if isinstance(value, str):
            # Try to resolve common UUID fields
            if _is_uuid(value):
                # Try to resolve as different object types
                resolved_value = _resolve_uuid_by_field(value, key)
                if resolved_value != value:
                    resolved[key] = resolved_value
                else:
                    resolved[key] = value
            else:
                resolved[key] = value
        elif isinstance(value, dict):
            # Recursively resolve nested dictionaries
            resolved[key] = _resolve_all_uuids(value, current_store)
        elif isinstance(value, list):
            # Handle lists of values
            resolved[key] = [
                _resolve_all_uuids(item, current_store) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            resolved[key] = value

    return resolved


def _is_uuid(value):
    """Check if a string is a valid UUID."""
    try:
        import uuid

        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _resolve_uuid_by_field(uuid_str, field_name):
    """Try to resolve a UUID based on the field name context.

    Args:
        uuid_str: The UUID string to resolve
        field_name: The field name to use as context

    Returns:
        Resolved name or original UUID if not found
    """
    # Import models here to avoid module-level import issues
    from apps.accounts.models import User
    from apps.permissions.models import Role, Permission
    from apps.stores.models import Store

    # Common field mappings for UUID resolution
    field_mappings = {
        # User fields
        "user": (User, "User"),
        "actor": (User, "User"),
        "invited_by": (User, "User"),
        "target_user": (User, "User"),
        "user_id": (User, "User"),
        # Role fields
        "role": (Role, "Role"),
        "role_id": (Role, "Role"),
        "new_role": (Role, "Role"),
        "previous_role": (Role, "Role"),
        "removed_role": (Role, "Role"),
        "inherits_from": (Role, "Role"),
        # Permission fields
        "permission": (Permission, "Permission"),
        "permission_id": (Permission, "Permission"),
        # Store fields
        "store": (Store, "Store"),
        "store_id": (Store, "Store"),
    }

    # Try to resolve based on field name
    field_name_lower = field_name.lower()

    for field_key, (model_class, model_name) in field_mappings.items():
        if field_key in field_name_lower or field_name_lower in field_key:
            try:
                obj = model_class.objects.get(id=uuid_str)

                # Return appropriate name based on object type
                if model_name == "User":
                    return obj.email or obj.get_full_name() or f"User: {uuid_str[:8]}"
                elif model_name == "Role":
                    return obj.name or f"Role: {uuid_str[:8]}"
                elif model_name == "Permission":
                    return obj.code or obj.name or f"Permission: {uuid_str[:8]}"
                elif model_name == "Store":
                    return obj.name or f"Store: {uuid_str[:8]}"
                else:
                    return str(obj)[:8]
            except Exception:
                return f"Deleted {model_name}: {uuid_str[:8]}"

    # If field-based resolution failed, try generic resolution
    try:
        import uuid

        uuid.UUID(uuid_str)  # Validate it's actually a UUID
    except:
        return uuid_str

    # Try resolving against common models
    for model_class, model_name in [
        (User, "User"),
        (Role, "Role"),
        (Permission, "Permission"),
        (Store, "Store"),
    ]:
        try:
            obj = model_class.objects.get(id=uuid_str)

            if model_name == "User":
                return obj.email or obj.get_full_name() or f"User: {uuid_str[:8]}"
            elif model_name == "Role":
                return obj.name or f"Role: {uuid_str[:8]}"
            elif model_name == "Permission":
                return obj.code or obj.name or f"Permission: {uuid_str[:8]}"
            elif model_name == "Store":
                return obj.name or f"Store: {uuid_str[:8]}"
        except Exception:
            continue

    return uuid_str[:8]  # Fallback to truncated UUID


@register.filter
def get_audit_action_description(action):
    """Get a user-friendly description for the audit action.

    Args:
        action: The audit action string (e.g., "member.invited")

    Returns:
        User-friendly description of the action
    """
    if not action:
        return "Unknown action"

    # Member management
    if action == "member.invited":
        return "Invited new team member"
    elif action == "member.reinvited":
        return "Reinvited team member"
    elif action == "member.activated":
        return "Activated team member"
    elif action == "member.deactivated":
        return "Deactivated team member"
    elif action == "member.removed":
        return "Removed team member"
    elif action == "member.role_changed":
        return "Changed team member role"

    # Role management
    elif action == "role.create":
        return "Created new role"
    elif action == "role.update":
        return "Updated role"
    elif action == "role.delete":
        return "Deleted role"
    elif action == "role.clone":
        return "Cloned role"
    elif action == "role.permission_granted":
        return "Granted permission to role"
    elif action == "role.permission_revoked":
        return "Revoked permission from role"

    # Permission override
    elif action == "override.created":
        return "Created user permission override"
    elif action == "override.updated":
        return "Updated user permission override"
    elif action == "override.deleted":
        return "Deleted user permission override"

    # Generic fallback
    parts = action.split(".")
    if len(parts) > 1:
        return f"{' '.join(word.capitalize() for word in parts[:-1])} {parts[-1].capitalize()}"
    else:
        return action.capitalize()


@register.filter
def get_target_name(target_type, target_id):
    """Get a human-readable name for the target instead of UUID.

    Args:
        target_type: The type of object (e.g., "User", "Role", "StoreMembership")
        target_id: The UUID of the target object

    Returns:
        Human-readable name, or fallback to truncated UUID
    """
    if not target_type or not target_id:
        return "Unknown"

    # Handle invalid or very short IDs - show as-is for better UX
    if len(target_id) < 8:
        return target_id

    try:
        # Try to validate as UUID first
        import uuid

        uuid.UUID(target_id)
    except (ValueError, AttributeError):
        # Not a valid UUID, return truncated version
        return target_id[:12]

    try:
        # Import models based on target type
        if target_type == "User":
            from apps.accounts.models import User

            try:
                obj = User.objects.get(id=target_id)
                return obj.email or obj.get_full_name() or f"User: {target_id[:8]}"
            except User.DoesNotExist:
                return f"Deleted User: {target_id[:8]}"

        elif target_type == "Role":
            from apps.permissions.models import Role

            try:
                obj = Role.objects.get(id=target_id)
                return obj.name or f"Role: {target_id[:8]}"
            except Role.DoesNotExist:
                return f"Deleted Role: {target_id[:8]}"

        elif target_type == "StoreMembership":
            from apps.permissions.models import StoreMembership

            try:
                membership = StoreMembership.objects.get(id=target_id)
                user_part = membership.user.email if membership.user else "Unknown User"
                role_part = membership.role.name if membership.role else "No Role"
                return f"{user_part} ({role_part})"
            except StoreMembership.DoesNotExist:
                return f"Deleted Membership: {target_id[:8]}"

        elif target_type == "Permission":
            from apps.permissions.models import Permission

            try:
                obj = Permission.objects.get(id=target_id)
                return obj.code or obj.name or f"Permission: {target_id[:8]}"
            except Permission.DoesNotExist:
                return f"Deleted Permission: {target_id[:8]}"

        elif target_type == "Store":
            from apps.stores.models import Store

            try:
                obj = Store.objects.get(id=target_id)
                return obj.name or f"Store: {target_id[:8]}"
            except Store.DoesNotExist:
                return f"Deleted Store: {target_id[:8]}"

        elif target_type == "UserPermissionOverride":
            from apps.permissions.models import UserPermissionOverride

            try:
                obj = UserPermissionOverride.objects.get(id=target_id)
                user_part = obj.user.email if obj.user else "Unknown"
                perm_part = obj.permission.code if obj.permission else "Unknown"
                return f"Override: {user_part} ({perm_part})"
            except UserPermissionOverride.DoesNotExist:
                return f"Deleted Override: {target_id[:8]}"

        # Fallback for unknown types
        return f"{target_type}: {target_id[:8]}"

    except Exception:
        # If anything goes wrong, fall back to truncated UUID
        return target_id[:12]


@register.simple_tag(takes_context=True)
def resolve_audit_target(context, target_type, target_id):
    """Resolve the actual object name for audit log display.

    Args:
        context: Template context
        target_type: The type of object (e.g., "User", "Role")
        target_id: The UUID of the target object

    Returns:
        Human-readable name for the target object
    """
    # Add resolved names to context for caching
    if not hasattr(context, "resolved_audit_targets"):
        context["resolved_audit_targets"] = {}

    cache_key = f"{target_type}:{target_id}"
    if cache_key in context["resolved_audit_targets"]:
        return context["resolved_audit_targets"][cache_key]

    result = get_target_name(target_type, target_id)
    context["resolved_audit_targets"][cache_key] = result
    return result


@register.filter
def resolve_audit_metadata(metadata, action=None):
    """Resolve all UUIDs in audit metadata to actual names.

    Args:
        metadata: Dictionary containing audit log metadata
        action: The audit action type (optional)

    Returns:
        Dictionary with all UUIDs resolved to actual names
    """
    if not metadata or not isinstance(metadata, dict):
        return metadata if metadata else {}

    return _resolve_all_uuids(metadata)
