"""
Seeds the default role → permission matrix.

Binds each system role to the permission codes it should grant. Idempotent.

Wildcards:
  - ``"*"``                    → all 'manage' permissions (effectively all
                                  resources, all actions)
  - ``"resource.*"``           → all actions for that resource
  - ``"resource.action"``      → a single permission code
"""

from __future__ import annotations

from apps.core.seeders.base import BaseSeeder
from apps.permissions.constants import MODIFIER_GRANT
from apps.permissions.models import Permission, Role, RolePermission


ROLE_PERMISSION_MATRIX: dict[str, set[str]] = {
    "store-owner": {"*"},
    "admin": {"*"},
    "manager": {
        "dashboard.view",
        "customers.view", "customers.create", "customers.update", "customers.export",
        "orders.view", "orders.create", "orders.update", "orders.approve", "orders.export",
        "products.view", "products.update",
        "inventory.view", "inventory.update", "inventory.export",
        "reports.view", "reports.export",
        "categories.view",
    },
    "sales-agent": {
        "dashboard.view",
        "customers.view", "customers.update", "customers.create",
        "orders.view", "orders.create", "orders.update",
    },
    "customer-support": {
        "dashboard.view",
        "customers.view", "customers.update",
        "orders.view", "orders.update",
        "returns.view", "returns.create", "returns.update",
    },
    "inventory-manager": {
        "dashboard.view",
        "products.view", "products.update",
        "inventory.view", "inventory.update", "inventory.export",
        "warehouses.view", "warehouses.update", "warehouses.create",
        "categories.view",
    },
    "marketing-executive": {
        "dashboard.view",
        "customers.view", "customer_groups.view", "customer_groups.create",
        "customer_groups.update",
        "campaigns.view", "campaigns.create", "campaigns.update",
        "campaigns.delete", "campaigns.approve",
        "promo_codes.view", "promo_codes.create", "promo_codes.update",
    },
    "accountant": {
        "dashboard.view",
        "orders.view", "orders.export",
        "reports.view", "reports.export",
    },
    "viewer": {
        "dashboard.view",
        "customers.view",
        "products.view",
        "orders.view",
        "reports.view",
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
                    perms_to_grant.extend(
                        Permission.objects.filter(code__startswith=f"{base}.")
                    )
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
