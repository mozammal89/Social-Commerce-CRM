"""
Seeds the default system roles.

Idempotent: running it twice has no effect.
"""

from __future__ import annotations

from apps.core.seeders.base import BaseSeeder
from apps.permissions.models import Role


SYSTEM_ROLES: list[tuple[str, str, int, str]] = [
    # slug, name, level, description
    ("store-owner", "Store Owner", Role.LEVEL_OWNER,
     "Full access to everything in the store."),
    ("admin", "Admin", Role.LEVEL_ADMIN,
     "All except billing ownership transfer."),
    ("manager", "Manager", Role.LEVEL_MANAGER,
     "Day-to-day operations."),
    ("sales-agent", "Sales Agent", 40, "Manage own pipeline."),
    ("customer-support", "Customer Support", 35,
     "Read+reply on customer/orders."),
    ("inventory-manager", "Inventory Manager", 40,
     "Stock and warehouses."),
    ("marketing-executive", "Marketing Executive", 40,
     "Campaigns and promos."),
    ("accountant", "Accountant", 40, "Orders and reports (read/finance)."),
    ("viewer", "Viewer", Role.LEVEL_VIEWER, "Read-only across the store."),
]


class RolesSeeder(BaseSeeder):
    name = "roles"

    def run(self) -> None:
        for slug, name, level, desc in SYSTEM_ROLES:
            Role.objects.update_or_create(
                slug=slug,
                store=None,
                defaults={
                    "name": name,
                    "level": level,
                    "description": desc,
                    "is_system": True,
                    "is_active": True,
                },
            )
