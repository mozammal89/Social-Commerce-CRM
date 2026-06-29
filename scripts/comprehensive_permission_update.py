#!/usr/bin/env python3
"""
Manual comprehensive update of ROLE_PERMISSION_MATRIX with all missing permissions
"""


def update_role_permission_matrix():
    """Update the ROLE_PERMISSION_MATRIX with all missing permissions"""

    # Read the current file
    with open("apps/permissions/seeders/permissions_seeder.py", "r") as f:
        content = f.read()

    # Find and replace the manager section to add delete permissions
    old_manager = """    "manager": {
        "dashboard.view",
        "customers.view", "customers.create", "customers.update", "customers.export",
        "orders.view", "orders.create", "orders.update", "orders.approve", "orders.export",
        "products.view", "products.update",
        "inventory.view", "inventory.update", "inventory.export",
        "reports.view", "reports.export",
        "categories.view",
        # Team Management UI: managers can see but not edit RBAC.
        "members.view",
        "roles.view",
        "permissions.view",
    },"""

    new_manager = """    "manager": {
        "dashboard.view",
        "customers.view", "customers.create", "customers.update", "customers.delete", "customers.export",
        "orders.view", "orders.create", "orders.update", "orders.delete", "orders.approve", "orders.export",
        "products.view", "products.update",
        "inventory.view", "inventory.update", "inventory.export",
        "reports.view", "reports.export",
        "categories.view",
        # Team Management UI: managers can see but not edit RBAC.
        "members.view",
        "roles.view",
        "permissions.view",
    },"""

    if old_manager in content:
        content = content.replace(old_manager, new_manager)
        print("✓ Added delete permissions to manager role")
    else:
        print("⚠ Manager role section not found or already updated")

    # Write the updated content back
    with open("apps/permissions/seeders/permissions_seeder.py", "w") as f:
        f.write(content)

    print("✓ Updated permissions_seeder.py")


def update_resources_seeder():
    """Create/update resources seeder with missing resources"""

    resources_code = '''"""
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
'''

    # Write the resources seeder
    with open("apps/permissions/seeders/resources_seeder.py", "w") as f:
        f.write(resources_code)

    print("✓ Created resources_seeder.py")


def generate_permissions_from_resources():
    """Generate permission codes from resource catalog"""

    permissions = []

    resources_code = [
        ("audit", ["view"]),
        ("campaigns", ["approve", "create", "delete", "update", "view"]),
        ("categories", ["view"]),
        ("customer_groups", ["create", "update", "view"]),
        ("customers", ["create", "delete", "export", "update", "view"]),
        ("dashboard", ["view"]),
        ("employees", ["delete"]),
        ("inventory", ["export", "update", "view"]),
        ("members", ["assign", "create", "delete", "manage", "update", "view"]),
        ("orders", ["approve", "create", "delete", "export", "update", "view"]),
        ("permissions", ["create", "delete", "override_grant", "update", "view"]),
        ("plan", ["changed", "create", "update"]),
        ("products", ["update", "view"]),
        ("promo_codes", ["create", "update", "view"]),
        ("reports", ["export", "view"]),
        ("returns", ["create", "update", "view"]),
        ("roles", ["create", "delete", "manage", "manage_system", "update", "view"]),
        ("warehouses", ["create", "update", "view"]),
    ]

    for resource, actions in resources_code:
        for action in actions:
            permissions.append(f"{resource}.{action}")

    return permissions


def main():
    print("🔧 Updating ROLE_PERMISSION_MATRIX...")
    update_role_permission_matrix()

    print("\n🔧 Creating resources seeder...")
    update_resources_seeder()

    print("\n📊 Permission Coverage Analysis:")
    all_permissions = generate_permissions_from_resources()
    print(f"  Total resources: 18")
    print(f"  Total permissions: {len(all_permissions)}")

    print("\n📝 All permissions to be seeded:")
    for perm in sorted(all_permissions):
        print(f"  {perm}")

    print("\n✅ All updates completed successfully!")
    print("\n📋 Next steps:")
    print("  1. Review the updated permissions_seeder.py")
    print("  2. Review the new resources_seeder.py")
    print(
        "  3. Run seeders: python manage.py seed resources && python manage.py seed role-permissions"
    )


if __name__ == "__main__":
    main()
