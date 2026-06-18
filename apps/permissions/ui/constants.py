"""
Permission code constants used by the role/permission management UI.

These are the permission codes required to access the various management
pages. They map to the codes defined in the registry for the permissions
app (see ``apps/permissions/registry.py``).
"""

# ---- Page-level access permissions ----------------------------------------
# Reading the corresponding management page.
PERM_ROLES_VIEW = "roles.view"
PERM_MEMBERS_VIEW = "members.view"
PERM_PERMISSIONS_VIEW = "permissions.view"
PERM_AUDIT_VIEW = "audit.view"

# ---- Mutation permissions -------------------------------------------------
# Mutating resources managed by the UI.
PERM_ROLES_MANAGE = "roles.manage"
PERM_MEMBERS_MANAGE = "members.manage"
PERM_OVERRIDE_GRANT = "permissions.override_grant"
PERM_SYSTEM_ROLES_MANAGE = "roles.manage_system"  # superuser only
