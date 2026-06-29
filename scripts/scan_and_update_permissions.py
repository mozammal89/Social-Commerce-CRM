#!/usr/bin/env python3
"""
Comprehensive script to scan codebase for permissions and update ROLE_PERMISSION_MATRIX
"""

import re
import os
import ast
import json


def scan_constants_files():
    """Scan for permission definitions in constants files"""
    permissions_found = set()

    # Look for specific constants files
    constants_files = [
        "apps/permissions/ui/constants.py",
        "apps/permissions/constants.py",
        "apps/permissions/ui/templatetags/rp_ui.py",
    ]

    for file_path in constants_files:
        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                content = f.read()

                # Look for ACTION_PERMISSIONS, AUDIT_ACTION_PERMISSIONS, etc.
                dict_patterns = [
                    r"ACTION_PERMISSIONS\s*=\s*\{([^\}]+)\}",
                    r"AUDIT_ACTION_PERMISSIONS\s*=\s*\{([^\}]+)\}",
                    r"PERMISSION_CODES\s*=\s*\{([^\}]+)\}",
                ]

                for pattern in dict_patterns:
                    matches = re.findall(pattern, content, re.DOTALL)
                    for match in matches:
                        # Extract permission-like patterns
                        perm_patterns = r'["\']([a-z_]+\.[a-z_]+)["\']'
                        perms = re.findall(perm_patterns, match)
                        for perm in perms:
                            if "." in perm and len(perm.split(".")) == 2:
                                permissions_found.add(perm)

    return permissions_found


def scan_seeder_files():
    """Scan for permissions in seeder files"""
    permissions_found = set()

    seeder_files = [
        "apps/permissions/seeders/permissions_seeder.py",
        "apps/permissions/seeders/features_seeder.py",
    ]

    for file_path in seeder_files:
        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                content = f.read()

                # Look for permission patterns
                perm_patterns = r'["\']([a-z_]+\.[a-z_]+)["\']'
                perms = re.findall(perm_patterns, content)
                for perm in perms:
                    if "." in perm and len(perm.split(".")) == 2:
                        permissions_found.add(perm)

    return permissions_found


def scan_views_and_test_files():
    """Scan for permissions in views and test files"""
    permissions_found = set()

    python_files = []
    for root, dirs, files in os.walk("."):
        dirs[:] = [
            d
            for d in dirs
            if d not in ["venv", "node_modules", ".git", "__pycache__", "migrations"]
        ]
        for file in files:
            if file.endswith(".py"):
                file_path = os.path.join(root, file)
                # Focus on views, tests, and permission-related files
                if any(
                    keyword in file_path.lower()
                    for keyword in ["views", "tests", "permissions", "services", "decorators"]
                ):
                    python_files.append(file_path)

    for file_path in python_files:
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

                # Look for specific permission patterns
                patterns = [
                    r'permission_required\s*\(\s*["\']([a-z_]+\.[a-z_]+)["\']',
                    r'user_has_permission\([^)]*["\']([a-z_]+\.[a-z_]+)["\']',
                    r'has_permission\([^)]*["\']([a-z_]+\.[a-z_]+)["\']',
                    r'Permission\.objects\.get\(code\s*=\s*["\']([a-z_]+\.[a-z_]+)["\']',
                ]

                for pattern in patterns:
                    matches = re.findall(pattern, content)
                    for match in matches:
                        if match and "." in match:
                            permissions_found.add(match)

                # Also look for decorator patterns like @permission_required
                decorator_pattern = r'@permission_required\(["\']([a-z_]+\.[a-z_]+)["\']'
                matches = re.findall(decorator_pattern, content)
                for match in matches:
                    if match:
                        permissions_found.add(match)

        except Exception as e:
            pass

    return permissions_found


def get_all_codebase_permissions():
    """Combine all permission scanning methods"""
    all_permissions = set()

    print("🔍 Scanning constants files...")
    all_permissions.update(scan_constants_files())
    print(f"  Found {len(scan_constants_files())} permissions in constants")

    print("🔍 Scanning seeder files...")
    all_permissions.update(scan_seeder_files())
    print(f"  Found {len(scan_seeder_files())} permissions in seeders")

    print("🔍 Scanning views and test files...")
    all_permissions.update(scan_views_and_test_files())
    print(f"  Found {len(scan_views_and_test_files())} permissions in code")

    return all_permissions


def extract_matrix_permissions():
    """Extract permissions from ROLE_PERMISSION_MATRIX"""
    matrix_permissions = set()

    try:
        with open("apps/permissions/seeders/permissions_seeder.py", "r") as f:
            content = f.read()

            # Extract permission codes from ROLE_PERMISSION_MATRIX
            perm_pattern = r'["\']([a-z_]+\.[a-z_]+)["\']'
            matches = re.findall(perm_pattern, content, re.IGNORECASE)
            for match in matches:
                matrix_permissions.add(match.lower())

    except Exception as e:
        print(f"Error extracting matrix permissions: {e}")

    return matrix_permissions


def categorize_permissions(permissions):
    """Categorize permissions by resource type"""
    categorized = {}

    for perm in permissions:
        if "." in perm:
            resource, action = perm.split(".")
            categorized.setdefault(resource, set()).add(action)

    return categorized


def analyze_missing_permissions(codebase_perms, matrix_perms):
    """Analyze and categorize missing permissions"""
    missing_perms = codebase_perms - matrix_perms

    # Categorize missing permissions
    missing_categorized = categorize_permissions(missing_perms)

    # Group by logical categories
    rbac_resources = ["roles", "permissions", "members", "employees"]
    sales_resources = ["customers", "orders", "returns", "products", "categories"]
    marketing_resources = ["campaigns", "customer_groups", "promo_codes"]
    inventory_resources = ["inventory", "warehouses"]
    reporting_resources = ["reports", "analytics", "dashboard"]
    admin_resources = ["audit", "plan"]

    categorized_missing = {
        "rbac": {},
        "sales": {},
        "marketing": {},
        "inventory": {},
        "reporting": {},
        "admin": {},
        "other": {},
    }

    for resource, actions in missing_categorized.items():
        if resource in rbac_resources:
            categorized_missing["rbac"][resource] = sorted(list(actions))
        elif resource in sales_resources:
            categorized_missing["sales"][resource] = sorted(list(actions))
        elif resource in marketing_resources:
            categorized_missing["marketing"][resource] = sorted(list(actions))
        elif resource in inventory_resources:
            categorized_missing["inventory"][resource] = sorted(list(actions))
        elif resource in reporting_resources:
            categorized_missing["reporting"][resource] = sorted(list(actions))
        elif resource in admin_resources:
            categorized_missing["admin"][resource] = sorted(list(actions))
        else:
            categorized_missing["other"][resource] = sorted(list(actions))

    return categorized_missing


def suggest_role_assignments(missing_categorized):
    """Suggest role assignments for missing permissions"""
    role_suggestions = {}

    # RBAC permissions - typically admin/manager
    for resource, actions in missing_categorized.get("rbac", {}).items():
        for action in actions:
            if action == "view":
                for role in ["admin", "manager"]:
                    role_suggestions.setdefault(role, set()).add(f"{resource}.{action}")
            elif action in ["create", "update"]:
                role_suggestions.setdefault("admin", set()).add(f"{resource}.{action}")
            elif action in ["delete", "manage", "manage_system", "override_grant", "assign"]:
                role_suggestions.setdefault("admin", set()).add(f"{resource}.{action}")

    # Sales permissions
    for resource, actions in missing_categorized.get("sales", {}).items():
        for action in actions:
            if action == "view":
                for role in ["sales-agent", "customer-support", "manager", "viewer"]:
                    role_suggestions.setdefault(role, set()).add(f"{resource}.{action}")
            elif action in ["create", "update"]:
                for role in ["sales-agent", "customer-support"]:
                    role_suggestions.setdefault(role, set()).add(f"{resource}.{action}")
            elif action == "delete":
                role_suggestions.setdefault("manager", set()).add(f"{resource}.{action}")
            elif action == "export":
                for role in ["sales-agent", "manager", "accountant"]:
                    role_suggestions.setdefault(role, set()).add(f"{resource}.{action}")

    # Marketing permissions
    for resource, actions in missing_categorized.get("marketing", {}).items():
        for action in actions:
            if action == "view":
                for role in ["marketing-executive", "manager", "viewer"]:
                    role_suggestions.setdefault(role, set()).add(f"{resource}.{action}")
            elif action in ["create", "update"]:
                role_suggestions.setdefault("marketing-executive", set()).add(
                    f"{resource}.{action}"
                )
            elif action in ["delete", "approve"]:
                role_suggestions.setdefault("marketing-executive", set()).add(
                    f"{resource}.{action}"
                )

    # Inventory permissions
    for resource, actions in missing_categorized.get("inventory", {}).items():
        for action in actions:
            if action == "view":
                for role in ["inventory-manager", "manager", "viewer"]:
                    role_suggestions.setdefault(role, set()).add(f"{resource}.{action}")
            elif action in ["create", "update"]:
                role_suggestions.setdefault("inventory-manager", set()).add(f"{resource}.{action}")
            elif action == "export":
                for role in ["inventory-manager", "manager", "accountant"]:
                    role_suggestions.setdefault(role, set()).add(f"{resource}.{action}")

    # Reporting permissions
    for resource, actions in missing_categorized.get("reporting", {}).items():
        for action in actions:
            if action == "view":
                for role in ["manager", "accountant", "viewer"]:
                    role_suggestions.setdefault(role, set()).add(f"{resource}.{action}")
            elif action == "export":
                for role in ["manager", "accountant"]:
                    role_suggestions.setdefault(role, set()).add(f"{resource}.{action}")

    # Admin permissions
    for resource, actions in missing_categorized.get("admin", {}).items():
        for action in actions:
            if action in ["view", "changed", "create", "update"]:
                role_suggestions.setdefault("admin", set()).add(f"{resource}.{action}")

    # Convert sets to sorted lists
    for role in role_suggestions:
        role_suggestions[role] = sorted(list(role_suggestions[role]))

    return role_suggestions


def generate_updated_role_permission_matrix(role_suggestions):
    """Generate the complete updated ROLE_PERMISSION_MATRIX"""

    # Read current matrix
    with open("apps/permissions/seeders/permissions_seeder.py", "r") as f:
        content = f.read()

    # Find the current ROLE_PERMISSION_MATRIX
    matrix_start = content.find("ROLE_PERMISSION_MATRIX: dict[str, set[str]] = {")
    if matrix_start == -1:
        print("Could not find ROLE_PERMISSION_MATRIX")
        return content

    matrix_end = content.find(
        "}\n\n\n# ---------------------------------------------------------------------------",
        matrix_start,
    )
    if matrix_end == -1:
        print("Could not find end of ROLE_PERMISSION_MATRIX")
        return content

    current_matrix = content[matrix_start : matrix_end + 1]

    # Update each role's permissions
    updated_matrix = current_matrix

    for role, new_perms in role_suggestions.items():
        # Find the role section
        role_pattern = rf'("{role}":\s*\{{([^}}]+)\}})'
        role_match = re.search(role_pattern, updated_matrix, re.DOTALL)

        if role_match:
            existing_section = role_match.group(0)
            existing_content = role_match.group(1)

            # Add new permissions if not already present
            added_perms = []
            for perm in new_perms:
                perm_with_quotes = f'"{perm}"'
                if perm_with_quotes not in existing_section:
                    added_perms.append(perm)

            if added_perms:
                # Add new permissions before the closing brace
                existing_content = existing_content.rstrip(" ")
                new_perms_text = ",\n        ".join([f'"{perm}"' for perm in added_perms])
                updated_content = existing_content + ",\n        " + new_perms_text + "\n    "

                updated_section = f'"{role}": {{' + updated_content + "}}"
                updated_matrix = updated_matrix.replace(existing_section, updated_section)

    # Replace the matrix in the content
    updated_content = content[:matrix_start] + updated_matrix + content[matrix_end + 1 :]

    return updated_content


def generate_updated_deny_matrix(missing_permissions):
    """Generate the complete updated ROLE_PERMISSION_DENY_MATRIX"""
    missing_perms_set = set(missing_permissions)

    # Read current deny matrix
    with open("apps/permissions/seeders/permissions_seeder.py", "r") as f:
        content = f.read()

    # Find the current ROLE_PERMISSION_DENY_MATRIX
    matrix_start = content.find("ROLE_PERMISSION_DENY_MATRIX: dict[str, set[str]] = {")
    if matrix_start == -1:
        return content

    matrix_end = content.find("\n\n\nclass RolePermissionsSeeder", matrix_start)
    if matrix_end == -1:
        return content

    current_matrix = content[matrix_start:matrix_end]

    # Add missing permissions to appropriate deny rules
    # Most non-admin roles should not have access to RBAC and admin permissions
    rbac_perms = {
        "roles.delete",
        "roles.manage",
        "roles.manage_system",
        "permissions.create",
        "permissions.update",
        "permissions.delete",
        "permissions.override_grant",
        "members.manage",
        "members.assign",
        "employees.delete",
    }

    admin_perms = {"audit.view", "plan.changed", "plan.create", "plan.update"}

    # Find missing RBAC and admin permissions
    missing_rbac = rbac_perms & missing_perms_set
    missing_admin = admin_perms & missing_perms_set

    # Add to non-admin roles
    roles_to_update = [
        "manager",
        "sales-agent",
        "customer-support",
        "inventory-manager",
        "marketing-executive",
        "accountant",
        "viewer",
    ]

    updated_matrix = current_matrix

    for role in roles_to_update:
        # Find the role section
        role_pattern = rf'("{role}":\s*\{{([^}}]+)\}})'
        role_match = re.search(role_pattern, updated_matrix, re.DOTALL)

        if role_match:
            existing_section = role_match.group(0)
            existing_content = role_match.group(1)

            # Add missing deny permissions
            missing_for_role = missing_rbac | missing_admin
            added_perms = []
            for perm in missing_for_role:
                perm_with_quotes = f'"{perm}"'
                if perm_with_quotes not in existing_section:
                    added_perms.append(perm)

            if added_perms:
                # Add new permissions before the closing brace
                existing_content = existing_content.rstrip(" ")
                new_perms_text = ",\n        " + ",\n        ".join(
                    [f'"{perm}"' for perm in added_perms]
                )
                updated_content = existing_content + new_perms_text + "\n    "

                updated_section = f'"{role}": {{' + updated_content + "}}"
                updated_matrix = updated_matrix.replace(existing_section, updated_section)

    # Replace the deny matrix in the content
    updated_content = content[:matrix_start] + updated_matrix + content[matrix_end:]

    return updated_content


def main():
    print("🔍 Scanning codebase for all permissions...")
    codebase_permissions = get_all_codebase_permissions()
    print(f"✓ Total unique permissions found: {len(codebase_permissions)}")

    print("\n📊 Extracting current ROLE_PERMISSION_MATRIX...")
    matrix_permissions = extract_matrix_permissions()
    print(f"✓ Permissions in matrix: {len(matrix_permissions)}")

    print("\n🔎 Finding missing permissions...")
    missing_permissions = codebase_permissions - matrix_permissions
    print(f"✓ Missing permissions: {len(missing_permissions)}")

    if missing_permissions:
        print("\n📝 Missing Permissions Analysis:")
        missing_categorized = analyze_missing_permissions(codebase_permissions, matrix_permissions)

        for category, resources in missing_categorized.items():
            if resources:
                print(f"\n  {category.upper()}:")
                for resource, actions in resources.items():
                    print(f"    {resource}: {', '.join(actions)}")

        print("\n🎯 Analyzing role assignments...")
        role_suggestions = suggest_role_assignments(missing_categorized)

        print("\n📊 Role Assignment Suggestions:")
        for role, perms in sorted(role_suggestions.items()):
            print(f"\n  {role}:")
            for perm in perms:
                print(f"    {perm}")

        print("\n📄 Generating updated ROLE_PERMISSION_MATRIX...")
        updated_content = generate_updated_role_permission_matrix(role_suggestions)

        print("📄 Generating updated ROLE_PERMISSION_DENY_MATRIX...")
        updated_content = generate_updated_deny_matrix(missing_permissions)

        # Write to updated file
        output_file = "apps/permissions/seeders/permissions_seeder_updated.py"
        with open(output_file, "w") as f:
            f.write(updated_content)

        print(f"✓ Updated file saved to {output_file}")
        print(f"\nNext: Review the file and replace permissions_seeder.py")

        # Also generate a summary report
        summary_file = "scripts/permission_update_summary.json"
        with open(summary_file, "w") as f:
            summary = {
                "total_permissions_found": len(codebase_permissions),
                "permissions_in_matrix": len(matrix_permissions),
                "missing_permissions": len(missing_permissions),
                "missing_permissions_list": sorted(list(missing_permissions)),
                "role_suggestions": {
                    role: perms for role, perms in sorted(role_suggestions.items())
                },
                "categorized_missing": missing_categorized,
            }
            json.dump(summary, f, indent=2)

        print(f"✓ Summary report saved to {summary_file}")
    else:
        print("✓ All permissions are already in the matrix!")


if __name__ == "__main__":
    main()
