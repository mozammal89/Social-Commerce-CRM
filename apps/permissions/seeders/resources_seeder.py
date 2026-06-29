"""
Seeder for permissions system resources and their actions.
"""

from apps.core.seeders.base import BaseSeeder
from apps.permissions.models import Resource

# Resource catalog: (code, name, category, actions)
RESOURCE_CATALOG = [
    ("audit", "Audit", "admin", ["view"]),
    ("campaigns", "Campaigns", "marketing", ["approve", "create", "delete", "update", "view"]),
    ("categories", "Categories", "catalog", ["view"]),
    ("customer_groups", "Customer Groups", "marketing", ["create", "update", "view"]),
    ("customers", "Customers", "sales", ["create", "delete", "export", "update", "view"]),
    ("dashboard", "Dashboard", "general", ["view"]),
    ("employees", "Employees", "team", ["delete"]),
    ("inventory", "Inventory", "operations", ["export", "update", "view"]),
    ("members", "Members", "team", ["assign", "create", "delete", "manage", "update", "view"]),
    ("orders", "Orders", "sales", ["approve", "create", "delete", "export", "update", "view"]),
    ("permissions", "Permissions", "admin", ["create", "delete", "override_grant", "update", "view"]),
    ("plan", "Plan", "general", ["changed", "create", "update"]),
    ("products", "Products", "catalog", ["update", "view"]),
    ("promo_codes", "Promo Codes", "marketing", ["create", "update", "view"]),
    ("reports", "Reports", "analytics", ["export", "view"]),
    ("returns", "Returns", "sales", ["create", "update", "view"]),
    ("roles", "Roles", "admin", ["create", "delete", "manage", "manage_system", "update", "view"]),
    ("warehouses", "Warehouses", "operations", ["create", "update", "view"]),
]

class ResourcesSeeder(BaseSeeder):
    name = "resources"

    def run(self) -> None:
        for code, name, category, actions in RESOURCE_CATALOG:
            Resource.objects.update_or_create(
                code=code,
                defaults={
                    "name": name,
                    "category": category,
                    "actions": actions,
                },
            )
