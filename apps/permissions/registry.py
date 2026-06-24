"""
Resource registry — single source of truth for Resources and Permissions.

Adding a new resource:
    1. Add an entry to RESOURCES.
    2. Run `python manage.py sync_permissions`.
    3. Done. The DB now has Resource + Permission rows. Roles and views
       can reference the new permission codes immediately.

Permission codes are stable strings. NEVER rename an existing code in a
way that breaks already-issued JWT claims or DB rows.
"""

from __future__ import annotations

from typing import Dict, List

from .constants import ACTIONS

# ---------------------------------------------------------------------------
# Standard actions (re-exported from constants for convenience)
# ---------------------------------------------------------------------------

# Keep an explicit list for type clarity in the registry.
ALL_ACTIONS: List[str] = list(ACTIONS)

# ---------------------------------------------------------------------------
# The Resource registry.
# Schema:
#   code:        stable lowercase identifier; permission codes derive from this.
#   name:        human label used in admin/UI.
#   category:    grouping for admin display ("core", "catalog", "sales", ...).
#   description: optional human description.
#   actions:     list of action verbs that apply to this resource.
# ---------------------------------------------------------------------------
RESOURCES: Dict[str, dict] = {
    "dashboard": {
        "name": "Dashboard",
        "category": "core",
        "description": "Home dashboard widgets and overview.",
        "actions": ["view"],
    },
    "customers": {
        "name": "Customers",
        "category": "core",
        "description": "CRM customer records.",
        "actions": ["view", "create", "update", "delete", "export", "import"],
    },
    "customer_groups": {
        "name": "Customer Groups",
        "category": "core",
        "description": "Customer segmentation.",
        "actions": ["view", "create", "update", "delete"],
    },
    "products": {
        "name": "Products",
        "category": "catalog",
        "description": "Product catalog.",
        "actions": ["view", "create", "update", "delete", "export", "import"],
    },
    "categories": {
        "name": "Categories",
        "category": "catalog",
        "description": "Product categories and taxonomy.",
        "actions": ["view", "create", "update", "delete"],
    },
    "inventory": {
        "name": "Inventory",
        "category": "catalog",
        "description": "Stock levels and movements.",
        "actions": ["view", "update", "export"],
    },
    "warehouses": {
        "name": "Warehouses",
        "category": "catalog",
        "description": "Warehouse locations.",
        "actions": ["view", "create", "update", "delete"],
    },
    "orders": {
        "name": "Orders",
        "category": "sales",
        "description": "Sales orders.",
        "actions": ["view", "create", "update", "delete", "approve", "export"],
    },
    "returns": {
        "name": "Returns",
        "category": "sales",
        "description": "Returns and refunds.",
        "actions": ["view", "create", "update", "approve"],
    },
    "couriers": {
        "name": "Couriers",
        "category": "sales",
        "description": "Shipping couriers.",
        "actions": ["view", "create", "update", "delete", "assign"],
    },
    "campaigns": {
        "name": "Marketing Campaigns",
        "category": "marketing",
        "description": "Email/SMS campaigns.",
        "actions": ["view", "create", "update", "delete", "approve"],
    },
    "promo_codes": {
        "name": "Promo Codes",
        "category": "marketing",
        "description": "Discount codes and vouchers.",
        "actions": ["view", "create", "update", "delete"],
    },
    "reports": {
        "name": "Reports",
        "category": "analytics",
        "description": "Reports and dashboards.",
        "actions": ["view", "create", "export"],
    },
    "employees": {
        "name": "Employees",
        "category": "team",
        "description": "Team members.",
        "actions": ["view", "create", "update", "delete", "assign"],
    },
    "members": {
        "name": "Store Members",
        "category": "team",
        "description": "Store team membership and role assignments.",
        "actions": ["view", "create", "update", "delete", "assign", "manage"],
    },
    "roles": {
        "name": "Roles & Permissions",
        "category": "team",
        "description": "Custom roles and their permission bindings.",
        "actions": ["view", "create", "update", "delete", "assign", "manage", "manage_system"],
    },
    "permissions": {
        "name": "Permission Overrides",
        "category": "team",
        "description": "User-specific permission overrides.",
        "actions": ["view", "create", "update", "delete", "override_grant"],
    },
    "integrations": {
        "name": "Integrations",
        "category": "platform",
        "description": "Third-party integrations (FB, WhatsApp, etc.).",
        "actions": ["view", "create", "update", "delete"],
    },
    "settings": {
        "name": "Store Settings",
        "category": "platform",
        "description": "Store configuration and preferences.",
        "actions": ["view", "update"],
    },
    "audit": {
        "name": "Audit Log",
        "category": "platform",
        "description": "Append-only record of RBAC changes.",
        "actions": ["view"],
    },
}


def iter_permissions() -> List[dict]:
    """
    Yield permission descriptors: {resource, action, code, name, description}.

    Used by sync_permissions and by tests.
    """
    out: List[dict] = []
    for resource_code, spec in RESOURCES.items():
        for action in spec["actions"]:
            code = f"{resource_code}.{action}"
            out.append(
                {
                    "resource": resource_code,
                    "action": action,
                    "code": code,
                    "name": f"{spec['name']} – {action.title()}",
                    "description": f"Permission to {action} {spec['name'].lower()}.",
                }
            )
    return out


def get_resource(code: str) -> dict | None:
    """Return the spec for a resource code, or None if not registered."""
    return RESOURCES.get(code)


def is_valid_permission_code(code: str) -> bool:
    """Quick structural check: 'resource.action' where action is known."""
    if "." not in code:
        return False
    resource_code, _, action = code.partition(".")
    spec = RESOURCES.get(resource_code)
    if spec is None:
        return False
    return action in spec["actions"]


def split_code(code: str) -> tuple[str, str] | None:
    """Split '<resource>.<action>' into (resource, action). Returns None if invalid."""
    if "." not in code:
        return None
    resource_code, _, action = code.partition(".")
    return (resource_code, action)
