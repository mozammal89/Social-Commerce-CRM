"""
Seeds the default role → permission matrix.

Binds each system role to the permission codes it should grant. Idempotent.

Wildcards:
  - ``"*"``                    → all 'manage' permissions (effectively all
                                  resources, all actions)
  - ``"resource.*"``           → all actions for that resource
  - ``"resource.action"``      → a single permission code

After the GRANT pass we apply ``ROLE_PERMISSION_DENY_MATRIX`` (Bug 13).
Wildcard ``"*"`` grants are then neutralised for any code that has a more
specific DENY row, preventing privilege escalation via broad grants.
"""

from __future__ import annotations

import logging

from apps.core.seeders.base import BaseSeeder
from apps.permissions.constants import MODIFIER_GRANT, MODIFIER_DENY
from apps.permissions.models import Permission, Role, RolePermission


logger = logging.getLogger(__name__)


ROLE_PERMISSION_MATRIX: dict[str, set[str]] = {
    "store-owner": {"*"},
    "admin": {"*"},
    "manager": {
        "dashboard.view",
        "customers.view",
        "customers.create",
        "customers.update",
        "customers.delete",
        "customers.export",
        "orders.view",
        "orders.create",
        "orders.update",
        "orders.delete",
        "orders.approve",
        "orders.export",
        "products.view",
        "products.update",
        "inventory.view",
        "inventory.update",
        "inventory.export",
        "reports.view",
        "reports.export",
        "categories.view",
        # Team Management UI: managers can see but not edit RBAC.
        "members.view",
        "roles.view",
        "permissions.view",
    },
    "sales-agent": {
        "dashboard.view",
        "customers.view",
        "customers.update",
        "customers.create",
        "orders.view",
        "orders.create",
        "orders.update",
        "members.view",
    },
    "customer-support": {
        "dashboard.view",
        "customers.view",
        "customers.update",
        "orders.view",
        "orders.update",
        "returns.view",
        "returns.create",
        "returns.update",
        "members.view",
    },
    "inventory-manager": {
        "dashboard.view",
        "products.view",
        "products.update",
        "inventory.view",
        "inventory.update",
        "inventory.export",
        "warehouses.view",
        "warehouses.update",
        "warehouses.create",
        "categories.view",
        "members.view",
    },
    "marketing-executive": {
        "dashboard.view",
        "customers.view",
        "customer_groups.view",
        "customer_groups.create",
        "customer_groups.update",
        "campaigns.view",
        "campaigns.create",
        "campaigns.update",
        "campaigns.delete",
        "campaigns.approve",
        "promo_codes.view",
        "promo_codes.create",
        "promo_codes.update",
        "members.view",
    },
    "accountant": {
        "dashboard.view",
        "orders.view",
        "orders.export",
        "reports.view",
        "reports.export",
        "members.view",
    },
    "viewer": {
        "dashboard.view",
        "customers.view",
        "products.view",
        "orders.view",
        "reports.view",
        "members.view",
    },
}


# ---------------------------------------------------------------------------
# Bug 13: explicit deny matrix.
#
# Applied AFTER the GRANT pass. Wildcard ``"*"`` grants are then neutralised
# for any code that has a more specific DENY row.
# ---------------------------------------------------------------------------
ROLE_PERMISSION_DENY_MATRIX: dict[str, set[str]] = {
    # ``store-owner`` keeps all grants (no denies).
    # ``admin`` cannot delete roles/permissions or override employee assignments.
    "admin": {
        "roles.delete",
        "permissions.delete",
        "employees.delete",
        # System role management is superuser-only.
        "roles.manage_system",
    },
    # Managers keep day-to-day access but cannot modify the RBAC system.
    "manager": {
        "roles.delete",
        "permissions.delete",
        "roles.create",
        "roles.update",
        "roles.manage",
        "permissions.create",
        "permissions.update",
        "permissions.override_grant",
        "employees.delete",
        "members.create",
        "members.update",
        "members.delete",
        "members.assign",
        "members.manage",
        "audit.view",
    },
    # Sales / support / inventory / marketing / accountant: same RBAC denies.
    "sales-agent": {
        "roles.delete",
        "permissions.delete",
        "employees.delete",
        "members.create",
        "members.update",
        "members.delete",
        "members.assign",
        "members.manage",
        "audit.view",
    },
    "customer-support": {
        "roles.delete",
        "permissions.delete",
        "employees.delete",
        "members.create",
        "members.update",
        "members.delete",
        "members.assign",
        "members.manage",
        "audit.view",
    },
    "inventory-manager": {
        "roles.delete",
        "permissions.delete",
        "employees.delete",
        "members.create",
        "members.update",
        "members.delete",
        "members.assign",
        "members.manage",
        "audit.view",
    },
    "marketing-executive": {
        "roles.delete",
        "permissions.delete",
        "employees.delete",
        "members.create",
        "members.update",
        "members.delete",
        "members.assign",
        "members.manage",
        "audit.view",
    },
    "accountant": {
        "roles.delete",
        "permissions.delete",
        "employees.delete",
        "members.create",
        "members.update",
        "members.delete",
        "members.assign",
        "members.manage",
        "audit.view",
    },
    # Viewers cannot touch RBAC either.
    "viewer": {
        "roles.delete",
        "permissions.delete",
        "employees.delete",
        "members.create",
        "members.update",
        "members.delete",
        "members.assign",
        "members.manage",
        "audit.view",
    },
}


class RolePermissionsSeeder(BaseSeeder):
    name = "role-permissions"

    def run(self) -> None:
        for role_slug, codes in ROLE_PERMISSION_MATRIX.items():
            try:
                role = Role.objects.get(slug=role_slug, store=None)
            except Role.DoesNotExist:
                # Roles not seeded yet — skip silently.
                continue

            perms_to_grant: list[Permission] = []

            for code in codes:
                if code == "*":
                    perms_to_grant.extend(Permission.objects.all())
                elif code.endswith(".*"):
                    base = code[:-2]
                    perms_to_grant.extend(Permission.objects.filter(code__startswith=f"{base}."))
                else:
                    try:
                        perms_to_grant.append(Permission.objects.get(code=code))
                    except Permission.DoesNotExist:
                        continue

            for perm in perms_to_grant:
                RolePermission.objects.update_or_create(
                    role=role,
                    permission=perm,
                    defaults={"modifier": MODIFIER_GRANT},
                )
            logger.info(
                "granted %d permissions to role %r",
                len(perms_to_grant),
                role_slug,
            )

        # ------------------------------------------------------------------
        # Bug 13: apply the deny matrix AFTER all grants are written.
        # ------------------------------------------------------------------
        for role_slug, codes in ROLE_PERMISSION_DENY_MATRIX.items():
            try:
                role = Role.objects.get(slug=role_slug, store=None)
            except Role.DoesNotExist:
                continue

            denied = 0
            for code in codes:
                try:
                    perm = Permission.objects.get(code=code)
                except Permission.DoesNotExist:
                    continue
                RolePermission.objects.update_or_create(
                    role=role,
                    permission=perm,
                    defaults={"modifier": MODIFIER_DENY},
                )
                denied += 1
            logger.info(
                "denied %d permissions to role %r (matrix)",
                denied,
                role_slug,
            )
