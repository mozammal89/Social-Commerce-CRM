"""
Constants for the RBAC system.

Stable identifiers used across code, fixtures, seeders, and tests.
Changing these values is a breaking change.
"""

# ---------------------------------------------------------------------------
# Actions — the verbs a permission can grant on a resource.
# Adding a new action here requires adding a Permission row per resource.
# ---------------------------------------------------------------------------
ACTIONS: tuple[str, ...] = (
    "view",
    "create",
    "update",
    "delete",
    "export",
    "import",
    "approve",
    "assign",
    "manage",  # wildcard: equivalent to "all actions on this resource"
)

ACTION_CHOICES: list[tuple[str, str]] = [
    ("view", "View"),
    ("create", "Create"),
    ("update", "Update"),
    ("delete", "Delete"),
    ("export", "Export"),
    ("import", "Import"),
    ("approve", "Approve"),
    ("assign", "Assign"),
    ("manage", "Manage (all actions)"),
]

# ---------------------------------------------------------------------------
# Modifiers for RolePermission — control how a role's permission is resolved.
# ---------------------------------------------------------------------------
MODIFIER_GRANT = "grant"
MODIFIER_DENY = "deny"
MODIFIER_DEFAULT = "default"

MODIFIER_CHOICES: list[tuple[str, str]] = [
    (MODIFIER_GRANT, "Grant"),
    (MODIFIER_DEFAULT, "Default"),
    (MODIFIER_DENY, "Deny"),
]

# ---------------------------------------------------------------------------
# Subscription status
# ---------------------------------------------------------------------------
SUB_TRIALING = "trialing"
SUB_ACTIVE = "active"
SUB_PAST_DUE = "past_due"
SUB_CANCELED = "canceled"
SUB_EXPIRED = "expired"

SUBSCRIPTION_STATUS_CHOICES: list[tuple[str, str]] = [
    (SUB_TRIALING, "Trialing"),
    (SUB_ACTIVE, "Active"),
    (SUB_PAST_DUE, "Past Due"),
    (SUB_CANCELED, "Canceled"),
    (SUB_EXPIRED, "Expired"),
]

# ---------------------------------------------------------------------------
# Default system role slugs.
# These are seeded by RolesSeeder and are referenced by data migrations.
# ---------------------------------------------------------------------------
ROLE_STORE_OWNER = "store-owner"
ROLE_ADMIN = "admin"
ROLE_MANAGER = "manager"
ROLE_SALES_AGENT = "sales-agent"
ROLE_CUSTOMER_SUPPORT = "customer-support"
ROLE_INVENTORY_MANAGER = "inventory-manager"
ROLE_MARKETING_EXECUTIVE = "marketing-executive"
ROLE_ACCOUNTANT = "accountant"
ROLE_VIEWER = "viewer"

DEFAULT_ROLES: tuple[str, ...] = (
    ROLE_STORE_OWNER,
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_SALES_AGENT,
    ROLE_CUSTOMER_SUPPORT,
    ROLE_INVENTORY_MANAGER,
    ROLE_MARKETING_EXECUTIVE,
    ROLE_ACCOUNTANT,
    ROLE_VIEWER,
)

# ---------------------------------------------------------------------------
# Default feature codes — used for plan gating.
# ---------------------------------------------------------------------------
DEFAULT_FEATURES: tuple[str, ...] = (
    "customer_management",
    "basic_reports",
    "inventory_management",
    "marketing_campaigns",
    "advanced_reports",
    "team_management",
    "multi_warehouse",
    "api_access",
    "facebook_integration",
    "whatsapp_integration",
    "sso",
    "audit_export",
)

# ---------------------------------------------------------------------------
# Subscription event types
# ---------------------------------------------------------------------------
EVENT_TRIAL_EXPIRED = "trial.expired"
EVENT_PERIOD_EXPIRED = "period.expired"
EVENT_PAYMENT_FAILED = "payment.failed"
EVENT_CANCELED = "subscription.canceled"
EVENT_REACTIVATED = "subscription.reactivated"
EVENT_RENEWED = "subscription.renewed"
EVENT_CREATED = "subscription.created"
EVENT_PLAN_CHANGED = "plan.changed"

# ---------------------------------------------------------------------------
# Audit action names.
# Convention: "<entity>.<verb>"
# ---------------------------------------------------------------------------
AUDIT_ROLE_CREATE = "role.create"
AUDIT_ROLE_UPDATE = "role.update"
AUDIT_ROLE_DELETE = "role.delete"
AUDIT_ROLE_PERMISSION_CREATE = "role_permission.create"
AUDIT_ROLE_PERMISSION_UPDATE = "role_permission.update"
AUDIT_ROLE_PERMISSION_DELETE = "role_permission.delete"
AUDIT_MEMBERSHIP_CREATE = "membership.create"
AUDIT_MEMBERSHIP_UPDATE = "membership.update"
AUDIT_MEMBERSHIP_DELETE = "membership.delete"
AUDIT_OVERRIDE_CREATE = "permission_override.create"
AUDIT_OVERRIDE_UPDATE = "permission_override.update"
AUDIT_OVERRIDE_DELETE = "permission_override.delete"
AUDIT_SUBSCRIPTION_CREATE = "subscription.create"
AUDIT_SUBSCRIPTION_UPDATE = "subscription.update"
AUDIT_PLAN_CREATE = "plan.create"
AUDIT_PLAN_UPDATE = "plan.update"
