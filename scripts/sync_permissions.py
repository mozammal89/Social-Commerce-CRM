#!/usr/bin/env python3
"""
Sync Permissions Script

This script scans the codebase for permission usage patterns and helps sync
the database with the codebase by identifying missing resources and actions.

Key features:
- Scans Python files for permission patterns using AST parsing
- Extracts permission codes from various patterns (decorators, function calls, etc.)
- Compares with database to find missing Resources and Actions
- Generates properly formatted seeder code
- Supports preview, dry-run, and interactive modes

Usage:
    python scripts/sync_permissions.py --help
    python scripts/sync_permissions.py scan --dry-run
    python scripts/sync_permissions.py sync --interactive
"""

import argparse
import ast
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Set, Dict, List, Tuple, Optional, Any

try:
    import django
    from django.conf import settings

    DJANGO_AVAILABLE = True
except ImportError:
    DJANGO_AVAILABLE = False


@dataclass
class PermissionUsage:
    """Represents a permission code found in the codebase."""

    code: str
    resource: str
    action: str
    files: List[str] = field(default_factory=list)
    line_numbers: List[int] = field(default_factory=list)
    context: List[str] = field(default_factory=list)


@dataclass
class ResourceInfo:
    """Represents a resource with its actions."""

    code: str
    name: str
    category: str
    actions: Set[str] = field(default_factory=set)
    found_in_codebase: bool = False


@dataclass
class SyncResult:
    """Contains the results of a sync operation."""

    total_permissions_scanned: int
    unique_permissions_found: int
    existing_resources: int
    existing_permissions: int
    missing_resources: List[ResourceInfo]
    missing_actions: Dict[str, Set[str]]
    new_permissions: List[Tuple[str, str]]
    scan_duration: float


class PermissionScanner(ast.NodeVisitor):
    """AST visitor that finds permission code patterns in Python code."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.permissions: List[PermissionUsage] = []
        self.permission_patterns = [
            (ast.Call, "user_has_permission"),
            (ast.Call, "has_permission"),
            (ast.Call, "permission_required"),
        ]
        self.false_positive_patterns = [
            r"^apps\.",
            r"^test_",
            r"^anything\.at_all$",
            r"^payment\.",
            r"^period\.",
            r"^trial\.",
            r"^subscription\.",
            r"^role\.",
            r"^role_permission\.",
            r"^membership\.",
            r"^permission_override\.",
        ]

    def visit_Call(self, node: ast.Call) -> None:
        """Visit function calls to find permission codes."""
        self._check_permission_call(node)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """Visit annotated assignments (e.g., permission_required = 'orders.view')."""
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            if self._is_permission_code(node.value.value):
                self._add_permission(
                    node.value.value,
                    node.lineno,
                    f"Assignment: {ast.unparse(node) if hasattr(ast, 'unparse') else 'variable assignment'}",
                )
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        """Visit assignments (e.g., permission_required = 'orders.view')."""
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            if self._is_permission_code(node.value.value):
                self._add_permission(
                    node.value.value,
                    node.lineno,
                    f"Assignment: {ast.unparse(node) if hasattr(ast, 'unparse') else 'variable assignment'}",
                )
        self.generic_visit(node)

    def visit_keyword(self, node: ast.keyword) -> None:
        """Visit keyword arguments (e.g., permission_required='orders.view')."""
        if node.arg == "permission_required" and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                if self._is_permission_code(node.value.value):
                    self._add_permission(
                        node.value.value,
                        node.lineno,
                        f"Keyword: permission_required={node.value.value}",
                    )
        self.generic_visit(node)

    def _check_permission_call(self, node: ast.Call) -> None:
        """Check if this is a permission-related function call."""
        func_name = None

        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name not in ["user_has_permission", "has_permission", "permission_required"]:
            return

        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if self._is_permission_code(arg.value):
                    self._add_permission(arg.value, node.lineno, f"Call: {func_name}({arg.value})")

        for keyword in node.keywords:
            if keyword.arg in ["code", "permission"]:
                if isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    if self._is_permission_code(keyword.value.value):
                        self._add_permission(
                            keyword.value.value,
                            node.lineno,
                            f"Call: {func_name}({keyword.arg}={keyword.value.value})",
                        )

    def _is_permission_code(self, value: str) -> bool:
        """Check if a string matches the permission code format."""
        pattern = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
        if not re.match(pattern, value.lower()):
            return False

        for fp_pattern in self.false_positive_patterns:
            if re.match(fp_pattern, value.lower()):
                return False

        known_actions = {
            "view",
            "create",
            "update",
            "delete",
            "export",
            "import",
            "approve",
            "assign",
            "manage",
            "override_grant",
            "manage_system",
        }

        _, action = value.split(".", 1)
        return action in known_actions or len(action) <= 20

    def _add_permission(self, code: str, line_no: int, context: str) -> None:
        """Add a permission to the list."""
        resource, action = code.split(".", 1)

        existing = next((p for p in self.permissions if p.code == code), None)
        if existing:
            existing.line_numbers.append(line_no)
            existing.context.append(context)
            if self.filepath not in existing.files:
                existing.files.append(self.filepath)
        else:
            self.permissions.append(
                PermissionUsage(
                    code=code,
                    resource=resource,
                    action=action,
                    files=[self.filepath],
                    line_numbers=[line_no],
                    context=[context],
                )
            )


class SeederScanner(ast.NodeVisitor):
    """AST visitor that finds permission patterns in seeder files."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.permissions: Set[str] = set()

    def visit_Dict(self, node: ast.Dict) -> None:
        """Visit dictionary literals (e.g., ROLE_PERMISSION_MATRIX)."""
        for value in node.values:
            if isinstance(value, ast.Set):
                for elt in value.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        if self._is_permission_code(elt.value):
                            self.permissions.add(elt.value)
            elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                if self._is_permission_code(value.value):
                    self.permissions.add(value.value)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        """Visit function calls for dynamic permission patterns."""
        func_name = None

        if isinstance(node.func, ast.Name):
            func_name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            func_name = node.func.attr

        if func_name in ["update_or_create", "get_or_create", "create"]:
            for keyword in node.keywords:
                if keyword.arg == "code" and isinstance(keyword.value, ast.Constant):
                    if isinstance(keyword.value.value, str) and self._is_permission_code(
                        keyword.value.value
                    ):
                        self.permissions.add(keyword.value.value)

        self.generic_visit(node)

    def _is_permission_code(self, value: str) -> bool:
        """Check if a string matches the permission code format."""
        pattern = r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$"
        if not re.match(pattern, value.lower()):
            return False

        false_positive_patterns = [
            r"^apps\.",
            r"^test_",
            r"^anything\.at_all$",
        ]

        for fp_pattern in false_positive_patterns:
            if re.match(fp_pattern, value.lower()):
                return False

        known_actions = {
            "view",
            "create",
            "update",
            "delete",
            "export",
            "import",
            "approve",
            "assign",
            "manage",
            "override_grant",
            "manage_system",
        }

        _, action = value.split(".", 1)
        return action in known_actions or len(action) <= 20


class PermissionSyncManager:
    """Main manager for permission scanning and syncing."""

    def __init__(self, project_root: str = None):
        self.project_root = Path(project_root) if project_root else Path(__file__).parent.parent
        self.apps_dir = self.project_root / "apps"
        self.scanned_permissions: Dict[str, PermissionUsage] = {}
        self.db_resources: Dict[str, ResourceInfo] = {}
        self.db_permissions: Set[str] = set()
        self.known_actions = self._get_known_actions()

    def _get_known_actions(self) -> Set[str]:
        """Get the set of known actions from the constants file."""
        actions_file = self.project_root / "apps" / "permissions" / "constants.py"
        if not actions_file.exists():
            return {
                "view",
                "create",
                "update",
                "delete",
                "export",
                "import",
                "approve",
                "assign",
                "manage",
            }

        actions = {
            "view",
            "create",
            "update",
            "delete",
            "export",
            "import",
            "approve",
            "assign",
            "manage",
        }
        try:
            with open(actions_file) as f:
                content = f.read()
                if "ACTIONS:" in content or "ACTION_CHOICES:" in content:
                    pattern = r'"([a-z_]+)"'
                    found = re.findall(pattern, content)
                    if found:
                        actions.update(found)
        except Exception:
            pass

        return actions

    def scan_codebase(self, include_seeder: bool = True) -> None:
        """Scan the entire codebase for permission usage patterns."""
        python_files = list(self.apps_dir.rglob("*.py"))

        for py_file in python_files:
            try:
                self._scan_file(py_file)
            except Exception as e:
                print(f"Warning: Failed to scan {py_file}: {e}")

        if include_seeder:
            self._scan_seeder_file()

    def _scan_file(self, filepath: Path) -> None:
        """Scan a single Python file for permission patterns."""
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                source = f.read()

            tree = ast.parse(source, filename=str(filepath))
            scanner = PermissionScanner(str(filepath.relative_to(self.project_root)))
            scanner.visit(tree)

            for perm in scanner.permissions:
                if perm.code not in self.scanned_permissions:
                    self.scanned_permissions[perm.code] = perm
                else:
                    existing = self.scanned_permissions[perm.code]
                    for file in perm.files:
                        if file not in existing.files:
                            existing.files.append(file)
                    existing.line_numbers.extend(perm.line_numbers)
                    existing.context.extend(perm.context)

        except SyntaxError:
            pass
        except Exception as e:
            print(f"Error scanning {filepath}: {e}")

    def _scan_seeder_file(self) -> None:
        """Scan the permissions_seeder.py file for hardcoded permissions."""
        seeder_file = (
            self.project_root / "apps" / "permissions" / "seeders" / "permissions_seeder.py"
        )
        if not seeder_file.exists():
            return

        try:
            with open(seeder_file, "r", encoding="utf-8") as f:
                source = f.read()

            tree = ast.parse(source, filename=str(seeder_file))
            scanner = SeederScanner(str(seeder_file.relative_to(self.project_root)))
            scanner.visit(tree)

            for code in scanner.permissions:
                resource, action = code.split(".", 1)
                if code not in self.scanned_permissions:
                    self.scanned_permissions[code] = PermissionUsage(
                        code=code,
                        resource=resource,
                        action=action,
                        files=[str(seeder_file.relative_to(self.project_root))],
                        line_numbers=[],
                        context=["From ROLE_PERMISSION_MATRIX"],
                    )

        except Exception as e:
            print(f"Error scanning seeder file: {e}")

    def query_database(self) -> None:
        """Query the database for existing Resources and Permissions."""
        if not DJANGO_AVAILABLE:
            print("Warning: Django not available. Skipping database query.")
            return

        try:
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
            django.setup()

            from apps.permissions.models import Resource, Permission

            for resource in Resource.objects.all():
                self.db_resources[resource.code] = ResourceInfo(
                    code=resource.code,
                    name=resource.name,
                    category=resource.category,
                    actions=set(resource.actions or []),
                    found_in_codebase=False,
                )

            for perm in Permission.objects.select_related("resource").all():
                code = f"{perm.resource.code}.{perm.action}"
                self.db_permissions.add(code)

        except Exception as e:
            print(f"Warning: Failed to query database: {e}")

    def analyze_gaps(self) -> Tuple[List[ResourceInfo], Dict[str, Set[str]]]:
        """Analyze gaps between codebase and database."""
        missing_resources = []
        missing_actions = defaultdict(set)

        codebase_resources = defaultdict(set)

        for code, perm in self.scanned_permissions.items():
            codebase_resources[perm.resource].add(perm.action)

        for resource_code, actions in codebase_resources.items():
            if resource_code not in self.db_resources:
                suggested_name = self._suggest_resource_name(resource_code)
                suggested_category = self._suggest_category(resource_code)

                missing_resources.append(
                    ResourceInfo(
                        code=resource_code,
                        name=suggested_name,
                        category=suggested_category,
                        actions=actions,
                        found_in_codebase=True,
                    )
                )
            else:
                db_resource = self.db_resources[resource_code]
                db_resource.found_in_codebase = True

                for action in actions:
                    if action not in db_resource.actions:
                        missing_actions[resource_code].add(action)

        return missing_resources, missing_actions

    def _suggest_resource_name(self, code: str) -> str:
        """Suggest a human-readable name for a resource code."""
        return code.replace("_", " ").title()

    def _suggest_category(self, code: str) -> str:
        """Suggest a category for a resource code."""
        category_map = {
            "dashboard": "general",
            "customers": "sales",
            "orders": "sales",
            "products": "catalog",
            "inventory": "operations",
            "warehouses": "operations",
            "reports": "analytics",
            "campaigns": "marketing",
            "promo_codes": "marketing",
            "customer_groups": "marketing",
            "categories": "catalog",
            "members": "team",
            "roles": "admin",
            "permissions": "admin",
            "audit": "admin",
            "returns": "sales",
            "employees": "team",
            "plans": "billing",
            "features": "billing",
            "subscriptions": "billing",
        }

        for key, category in category_map.items():
            if key in code:
                return category

        return "general"

    def generate_seeder_code(
        self, missing_resources: List[ResourceInfo], missing_actions: Dict[str, Set[str]]
    ) -> str:
        """Generate properly formatted seeder code."""
        code = []

        code.append(
            "# Resources to add to apps/permissions/seeders/resources_seeder.py or similar:"
        )
        code.append("#")
        code.append("# RESOURCE_CATALOG: list[tuple[str, str, str, list[str]]] = [")
        code.append("#     # (code, name, category, actions)")

        for resource in sorted(missing_resources, key=lambda r: r.code):
            actions_str = ", ".join(f'"{a}"' for a in sorted(resource.actions))
            code.append(
                f'#     ("{resource.code}", "{resource.name}", "{resource.category}", [{actions_str}]),'
            )

        for resource_code, actions in sorted(missing_actions.items()):
            if resource_code in self.db_resources:
                resource = self.db_resources[resource_code]
                existing_actions = resource.actions
                new_actions = sorted(actions - existing_actions)
                if new_actions:
                    actions_str = ", ".join(f'"{a}"' for a in new_actions)
                    code.append(
                        f'#     # Resource "{resource_code}" exists, add actions: [{actions_str}]'
                    )

        code.append("# ]")
        code.append("")

        code.append("# Permissions to add to ROLE_PERMISSION_MATRIX in permissions_seeder.py:")
        code.append("# These are examples; assign to appropriate roles based on your needs.")

        new_permissions = []
        for resource in sorted(missing_resources, key=lambda r: r.code):
            for action in sorted(resource.actions):
                code_str = f'"{resource.code}.{action}"'
                new_permissions.append(code_str)

        for resource_code, actions in sorted(missing_actions.items()):
            for action in sorted(actions):
                code_str = f'"{resource_code}.{action}"'
                if code_str not in new_permissions:
                    new_permissions.append(code_str)

        if new_permissions:
            code.append("#")
            code.append("# Example: Add to appropriate role permissions:")
            code.append('# "manager": {')
            for perm in new_permissions[:5]:
                code.append(f"#     {perm},")
            if len(new_permissions) > 5:
                code.append(f"#     # ... {len(new_permissions) - 5} more permissions")
            code.append("# },")

        return "\n".join(code)

    def print_summary(self, dry_run: bool = True) -> None:
        """Print a summary of the scan results."""
        print("\n" + "=" * 70)
        print("PERMISSION SCAN SUMMARY")
        print("=" * 70)

        print(f"\n📊 Statistics:")
        print(f"  Total permissions scanned: {len(self.scanned_permissions)}")
        print(f"  Unique permission codes found: {len(self.scanned_permissions)}")
        print(f"  Existing resources in database: {len(self.db_resources)}")
        print(f"  Existing permissions in database: {len(self.db_permissions)}")

        missing_resources, missing_actions = self.analyze_gaps()

        print(f"\n🔍 Gap Analysis:")
        print(f"  Missing resources: {len(missing_resources)}")
        print(f"  Missing actions for existing resources: {len(missing_actions)}")

        if missing_resources:
            print(f"\n📝 Missing Resources:")
            for resource in sorted(missing_resources, key=lambda r: r.code):
                print(f"  - {resource.code:20} ({resource.name})")
                print(f"    Category: {resource.category}")
                print(f"    Actions:  {', '.join(sorted(resource.actions))}")
                perm = self.scanned_permissions.get(f"{resource.code}.{list(resource.actions)[0]}")
                if perm and perm.files:
                    print(f"    Found in: {', '.join(perm.files[:2])}")

        if missing_actions:
            print(f"\n📝 Missing Actions for Existing Resources:")
            for resource_code, actions in sorted(missing_actions.items()):
                print(f"  - {resource_code}: {', '.join(sorted(actions))}")

        total_new_permissions = sum(len(r.actions) for r in missing_resources) + sum(
            len(a) for a in missing_actions.values()
        )

        if total_new_permissions > 0:
            print(f"\n📌 Total new permissions to create: {total_new_permissions}")

            if dry_run:
                print("\n🔒 DRY RUN MODE - No changes will be made")
                print("\nTo apply changes, run:")
                print("  python scripts/sync_permissions.py sync")
                print("  python scripts/sync_permissions.py sync --interactive")
            else:
                print("\n💡 Next steps:")
                print("  1. Review the generated seeder code above")
                print("  2. Add missing resources to your resource seeder")
                print("  3. Add missing permissions to appropriate roles")
                print("  4. Run your seeder scripts")

        if not missing_resources and not missing_actions:
            print("\n✅ All permissions are in sync!")

        print("\n" + "=" * 70)

    def print_detailed_usage(self, limit: int = 10) -> None:
        """Print detailed permission usage information."""
        print("\n📋 Detailed Permission Usage (showing first {}):".format(limit))
        print("-" * 70)

        for i, (code, perm) in enumerate(sorted(self.scanned_permissions.items())[:limit]):
            print(f"\n{i + 1}. {code}")
            print(f"   Resource: {perm.resource}")
            print(f"   Action:   {perm.action}")
            print(f"   Files:    {', '.join(perm.files[:3])}")
            if perm.line_numbers:
                print(f"   Lines:    {', '.join(map(str, perm.line_numbers[:3]))}")
            if perm.context:
                print(f"   Context:  {perm.context[0][:60]}...")

        if len(self.scanned_permissions) > limit:
            print(f"\n... and {len(self.scanned_permissions) - limit} more permissions")


def main():
    """Main entry point for the script."""
    parser = argparse.ArgumentParser(
        description="Scan and sync permissions in the codebase",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Scan the codebase and show gaps (dry run)
  python scripts/sync_permissions.py scan
  
  # Scan with detailed usage information
  python scripts/sync_permissions.py scan --verbose
  
  # Generate seeder code for missing items
  python scripts/sync_permissions.py generate
  
  # Interactive sync mode
  python scripts/sync_permissions.py sync --interactive
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    scan_parser = subparsers.add_parser("scan", help="Scan codebase for permissions")
    scan_parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Show what would be done (default: True)",
    )
    scan_parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed permission usage"
    )
    scan_parser.add_argument(
        "--limit", type=int, default=10, help="Limit detailed output (default: 10)"
    )

    generate_parser = subparsers.add_parser("generate", help="Generate seeder code")
    generate_parser.add_argument("--output", "-o", type=str, help="Output file (default: stdout)")

    sync_parser = subparsers.add_parser("sync", help="Sync permissions interactively")
    sync_parser.add_argument(
        "--interactive", "-i", action="store_true", help="Interactive mode with review prompts"
    )
    sync_parser.add_argument(
        "--force", "-f", action="store_true", help="Force sync without confirmation"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    print("🔍 Permission Sync Tool")
    print("=" * 70)

    manager = PermissionSyncManager()

    print("\n📂 Scanning codebase...")
    manager.scan_codebase()

    if args.command in ["sync", "generate"]:
        print("🗄️  Querying database...")
        manager.query_database()

    if args.command == "scan":
        if args.verbose:
            manager.print_detailed_usage(args.limit)
        manager.print_summary(dry_run=args.dry_run)

    elif args.command == "generate":
        missing_resources, missing_actions = manager.analyze_gaps()
        seeder_code = manager.generate_seeder_code(missing_resources, missing_actions)

        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w") as f:
                f.write(seeder_code)
            print(f"\n✅ Seeder code written to {output_path}")
        else:
            print("\n" + "=" * 70)
            print("GENERATED SEEDER CODE")
            print("=" * 70)
            print(seeder_code)

    elif args.command == "sync":
        missing_resources, missing_actions = manager.analyze_gaps()
        seeder_code = manager.generate_seeder_code(missing_resources, missing_actions)

        print("\n" + "=" * 70)
        print("SYNC PLAN")
        print("=" * 70)
        print(seeder_code)

        if not args.force:
            if args.interactive:
                response = input("\n❓ Do you want to proceed with these changes? [y/N]: ")
                if response.lower() != "y":
                    print("❌ Sync cancelled.")
                    sys.exit(0)
            else:
                print("\n⚠️  Use --force or --interactive to apply changes.")
                print("❌ Sync cancelled.")
                sys.exit(0)

        print("\n✅ Sync completed!")
        print("📝 Next steps:")
        print("  1. Review and update your seeder files")
        print("  2. Run: python manage.py seed permissions")
        print("  3. Run: python manage.py seed roles")
        print("  4. Run: python manage.py seed role-permissions")


if __name__ == "__main__":
    main()
