"""
Django Management Command: Permission Management

Advanced permission management commands for RBAC system.

Usage:
    python manage.py permission --help
    python manage.py permission --list
    python manage.py permission --sync
    python manage.py permission --audit
    python manage.py permission --test <permission_code>
    python manage.py permission --show-roles <permission_code>
"""

from django.core.management.base import BaseCommand, CommandError
from django.db import models
from django.db.models import Q
from typing import Optional, List, Set
import os
import re
import ast
import sys


class Command(BaseCommand):
    help = "Manage RBAC permissions system"

    def add_arguments(self, parser):
        parser.add_argument(
            "--list", action="store_true", help="List all permissions and their assigned roles"
        )
        parser.add_argument(
            "--sync", action="store_true", help="Sync permissions from codebase to database"
        )
        parser.add_argument(
            "--audit", action="store_true", help="Find gaps between codebase and database"
        )
        parser.add_argument("--test", type=str, help="Test a specific permission code")
        parser.add_argument(
            "--show-roles", type=str, help="Show which roles have a specific permission"
        )
        parser.add_argument(
            "--interactive", action="store_true", help="Interactive mode with prompts"
        )
        parser.add_argument(
            "--dry-run", action="store_true", help="Preview changes without applying them"
        )
        parser.add_argument("--verbose", action="store_true", help="Verbose output")

    def handle(self, *args, **options):
        if options["list"]:
            self.list_permissions()
        elif options["sync"]:
            self.sync_permissions(
                interactive=options["interactive"],
                dry_run=options["dry_run"],
                verbose=options["verbose"],
            )
        elif options["audit"]:
            self.audit_permissions()
        elif options["test"]:
            self.test_permission(options["test"])
        elif options["show_roles"]:
            self.show_permission_roles(options["show_roles"])
        else:
            self.print_help()

    def list_permissions(self):
        """List all permissions and their assigned roles"""
        from apps.permissions.models import Permission, Role

        permissions = Permission.objects.select_related("resource").order_by("code")

        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS("RBAC PERMISSIONS CATALOG"))
        self.stdout.write(self.style.SUCCESS("=" * 80))

        for permission in permissions:
            resource_name = permission.resource.name
            self.stdout.write(f"\n📋 {permission.code}")
            self.stdout.write(f"   Resource: {resource_name} ({permission.resource.category})")
            self.stdout.write(f"   Action: {permission.action}")

            # Show which roles have this permission
            roles_with_grant = []
            roles_with_deny = []

            role_permissions = permission.rolepermission_set.select_related("role").all()
            for rp in role_permissions:
                role_name = rp.role.name
                if rp.modifier == "grant":
                    roles_with_grant.append(role_name)
                elif rp.modifier == "deny":
                    roles_with_deny.append(role_name)

            if roles_with_grant:
                self.stdout.write(f"   ✅ Granted to: {', '.join(roles_with_grant)}")
            if roles_with_deny:
                self.stdout.write(f"   ❌ Denied to: {', '.join(roles_with_deny)}")

        self.stdout.write(f"\n{'=' * 80}")
        self.stdout.write(self.style.SUCCESS(f"Total Permissions: {permissions.count()}"))
        self.stdout.write(self.style.SUCCESS("=" * 80))

    def sync_permissions(self, interactive=False, dry_run=False, verbose=False):
        """Sync permissions from codebase to database"""
        from apps.permissions.models import Resource, Permission

        self.stdout.write(self.style.WARNING("=" * 80))
        self.stdout.write(self.style.WARNING("PERMISSION SYNC - CODEBASE → DATABASE"))
        self.stdout.write(self.style.WARNING("=" * 80))

        # Step 1: Scan codebase for permissions
        if verbose:
            self.stdout.write("\n🔍 Step 1: Scanning codebase for permissions...")

        codebase_permissions = self.scan_codebase_permissions()

        if verbose:
            self.stdout.write(f"   Found {len(codebase_permissions)} permissions in codebase")
            for perm in sorted(codebase_permissions):
                self.stdout.write(f"      - {perm}")

        # Step 2: Get current database permissions
        if verbose:
            self.stdout.write("\n🗄️ Step 2: Getting current database permissions...")

        db_permissions = set(Permission.objects.values_list("code", flat=True))

        if verbose:
            self.stdout.write(f"   Found {len(db_permissions)} permissions in database")
            for perm in sorted(db_permissions):
                self.stdout.write(f"      - {perm}")

        # Step 3: Find missing permissions
        missing_permissions = codebase_permissions - db_permissions
        extra_permissions = db_permissions - codebase_permissions

        if verbose:
            self.stdout.write(f"\n📊 Step 3: Analyzing differences...")
            self.stdout.write(f"   Missing in database: {len(missing_permissions)}")
            self.stdout.write(f"   Extra in database: {len(extra_permissions)}")

        # Step 4: Show summary
        self.stdout.write(f"\n📋 SYNC SUMMARY:")
        self.stdout.write(f"   Codebase permissions: {len(codebase_permissions)}")
        self.stdout.write(f"   Database permissions: {len(db_permissions)}")
        self.stdout.write(f"   Missing to add: {len(missing_permissions)}")
        self.stdout.write(f"   Extra to remove: {len(extra_permissions)}")

        if missing_permissions:
            self.stdout.write(f"\n   Missing permissions:")
            for perm in sorted(missing_permissions):
                self.stdout.write(f"      - {perm}")

        if extra_permissions:
            self.stdout.write(f"\n   Extra permissions (not in code):")
            for perm in sorted(extra_permissions):
                self.stdout.write(f"      - {perm}")

        # Step 5: Ask for confirmation if interactive
        if interactive:
            self.stdout.write(f"\n❓ Do you want to proceed with sync? (yes/no)")
            response = input().strip().lower()
            if response not in ["yes", "y"]:
                self.stdout.write(self.style.WARNING("Sync cancelled."))
                return

        # Step 6: Apply changes (unless dry run)
        if dry_run:
            self.stdout.write(f"\n🔒 DRY RUN MODE - No changes will be made")
            return

        if missing_permissions:
            if verbose:
                self.stdout.write(f"\n🔧 Adding {len(missing_permissions)} missing permissions...")

            added_count = 0
            for perm_code in missing_permissions:
                try:
                    resource_code, action = perm_code.split(".")
                    # Get or create resource
                    resource, created = Resource.objects.get_or_create(
                        code=resource_code,
                        defaults={
                            "name": resource_code.replace("_", " ").title(),
                            "category": "general",
                            "actions": [action],
                        },
                    )

                    # Add action to resource if not present
                    if action not in resource.actions:
                        resource.actions.append(action)
                        resource.save()

                    # Create permission
                    Permission.objects.get_or_create(
                        code=perm_code, defaults={"resource": resource, "action": action}
                    )
                    added_count += 1

                    if verbose:
                        self.stdout.write(f"      ✓ Added: {perm_code}")

                except Exception as e:
                    if verbose:
                        self.stdout.write(
                            self.style.ERROR(f"      ✗ Failed to add {perm_code}: {e}")
                        )

            self.stdout.write(
                self.style.SUCCESS(f"\n✅ Added {added_count} permissions to database")
            )

        if extra_permissions:
            self.stdout.write(
                self.style.WARNING(
                    f"\n⚠️  Found {len(extra_permissions)} extra permissions in database"
                )
            )
            self.stdout.write(
                f"   These may be removed with: python manage.py permission --cleanup"
            )

        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS("SYNC COMPLETE"))
        self.stdout.write(self.style.SUCCESS("=" * 80))

        # Final stats
        final_count = Permission.objects.count()
        self.stdout.write(f"\n📊 Final database state:")
        self.stdout.write(f"   Resources: {Resource.objects.count()}")
        self.stdout.write(f"   Permissions: {final_count}")

    def audit_permissions(self):
        """Audit permission system for gaps and issues"""
        from apps.permissions.models import Permission, Resource, Role

        self.stdout.write(self.style.WARNING("=" * 80))
        self.stdout.write(self.style.WARNING("RBAC SYSTEM AUDIT"))
        self.stdout.write(self.style.WARNING("=" * 80))

        # Step 1: Scan codebase
        codebase_permissions = self.scan_codebase_permissions()

        # Step 2: Get database state
        db_permissions = set(Permission.objects.values_list("code", flat=True))
        db_resources = set(Resource.objects.values_list("code", flat=True))

        # Step 3: Find gaps
        missing_permissions = codebase_permissions - db_permissions
        extra_permissions = db_permissions - codebase_permissions

        # Step 4: Check role assignments
        unassigned_permissions = set()
        orphan_permissions = set()

        all_permissions = Permission.objects.all()
        for perm in all_permissions:
            # Check if permission is assigned to any role
            if not perm.role_bindings.exists():
                unassigned_permissions.add(perm.code)

            # Check if permission has no resource (shouldn't happen)
            if not perm.resource:
                orphan_permissions.add(perm.code)

        # Step 5: Display results
        self.stdout.write(f"\n📊 AUDIT RESULTS:")

        # Permission gaps
        self.stdout.write(f"\n1️⃣ PERMISSION GAPS:")
        if missing_permissions:
            self.stdout.write(
                f"   {len(missing_permissions)} permissions in code but not in database:"
            )
            for perm in sorted(missing_permissions):
                self.stdout.write(f"      - {perm}")
        else:
            self.stdout.write(self.style.SUCCESS("   ✓ No missing permissions"))

        # Extra permissions
        self.stdout.write(f"\n2️⃣ EXTRA PERMISSIONS:")
        if extra_permissions:
            self.stdout.write(
                f"   {len(extra_permissions)} permissions in database but not in code:"
            )
            for perm in sorted(extra_permissions):
                self.stdout.write(f"      - {perm}")
        else:
            self.stdout.write(self.style.SUCCESS("   ✓ No extra permissions"))

        # Unassigned permissions
        self.stdout.write(f"\n3️⃣ UNASSIGNED PERMISSIONS:")
        if unassigned_permissions:
            self.stdout.write(
                f"   {len(unassigned_permissions)} permissions not assigned to any role:"
            )
            for perm in sorted(unassigned_permissions):
                self.stdout.write(f"      - {perm}")
        else:
            self.stdout.write(self.style.SUCCESS("   ✓ All permissions are assigned"))

        # Orphan permissions
        if orphan_permissions:
            self.stdout.write(f"\n4️⃣ ORPHAN PERMISSIONS:")
            self.stdout.write(f"   {len(orphan_permissions)} permissions without resources:")
            for perm in sorted(orphan_permissions):
                self.stdout.write(f"      - {perm}")

        # Summary
        self.stdout.write(f"\n📋 SUMMARY:")
        self.stdout.write(f"   Codebase permissions: {len(codebase_permissions)}")
        self.stdout.write(f"   Database permissions: {len(db_permissions)}")
        self.stdout.write(f"   Resources: {len(db_resources)}")
        self.stdout.write(f"   Roles: {Role.objects.filter(store=None).count()} (system)")
        self.stdout.write(
            f"   Issues found: {len(missing_permissions) + len(extra_permissions) + len(unassigned_permissions)}"
        )

        self.stdout.write(self.style.SUCCESS("=" * 80))

    def test_permission(self, permission_code):
        """Test a specific permission"""
        from apps.permissions.models import Permission
        from apps.accounts.models import User
        from apps.stores.models import Store
        from apps.permissions.services import user_has_permission

        self.stdout.write(self.style.WARNING("=" * 80))
        self.stdout.write(self.style.WARNING(f"TESTING PERMISSION: {permission_code}"))
        self.stdout.write(self.style.WARNING("=" * 80))

        # Check if permission exists
        try:
            permission = Permission.objects.get(code=permission_code)
            self.stdout.write(self.style.SUCCESS(f"✓ Permission exists in database"))
            self.stdout.write(f"   Resource: {permission.resource.name}")
            self.stdout.write(f"   Action: {permission.action}")
        except Permission.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"✗ Permission not found in database"))
            self.stdout.write(f"   Hint: Run 'python manage.py permission --sync' to create it")
            return

        # Show role assignments
        self.stdout.write(f"\n📋 ROLE ASSIGNMENTS:")
        role_permissions = permission.rolepermission_set.select_related("role").all()

        if not role_permissions:
            self.stdout.write(f"   No roles assigned to this permission")
        else:
            for rp in role_permissions:
                role_name = rp.role.name
                modifier = rp.modifier.upper()
                icon = "✅" if rp.modifier == "grant" else "❌"
                self.stdout.write(f"   {icon} {role_name} ({modifier})")

        # Test with actual users
        self.stdout.write(f"\n👥 USER TESTING:")
        users = User.objects.all()[:5]  # Test first 5 users

        if not users:
            self.stdout.write(f"   No users found in database")
            return

        stores = Store.objects.all()[:1]  # Test with first store
        if not stores:
            self.stdout.write(f"   No stores found in database")
            return

        store = stores[0]

        for user in users:
            has_perm = user_has_permission(user, store, permission_code)
            status = "✅" if has_perm else "❌"
            user_role = "No role"

            # Try to get user's role
            try:
                user_role = user.roles.filter(store=store).first()
                if user_role:
                    user_role = user_role.role.name
            except:
                pass

            self.stdout.write(f"   {status} {user.email} ({user_role})")

    def show_permission_roles(self, permission_code):
        """Show which roles have a specific permission"""
        from apps.permissions.models import Permission
        from apps.permissions.models import Role

        try:
            permission = Permission.objects.get(code=permission_code)
        except Permission.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Permission '{permission_code}' not found"))
            return

        self.stdout.write(self.style.SUCCESS("=" * 80))
        self.stdout.write(self.style.SUCCESS(f"ROLES WITH PERMISSION: {permission_code}"))
        self.stdout.write(self.style.SUCCESS("=" * 80))

        role_permissions = permission.rolepermission_set.select_related("role").order_by(
            "role__name"
        )

        if not role_permissions:
            self.stdout.write(f"No roles assigned to this permission")
            return

        for rp in role_permissions:
            role = rp.role
            modifier = rp.modifier.upper()
            icon = "✅" if rp.modifier == "grant" else "❌"

            self.stdout.write(f"\n{icon} {role.name}")
            self.stdout.write(f"   Slug: {role.slug}")
            self.stdout.write(f"   Modifier: {modifier}")

            if role.store:
                self.stdout.write(f"   Store: {role.store.name}")
            else:
                self.stdout.write(f"   Store: System Role")

        self.stdout.write(f"\n{'=' * 80}")
        self.stdout.write(self.style.SUCCESS(f"Total: {role_permissions.count()} roles"))
        self.stdout.write(self.style.SUCCESS("=" * 80))

    def scan_codebase_permissions(self) -> Set[str]:
        """Scan codebase for all permission patterns"""
        permissions_found = set()

        # Scan Python files
        for root, dirs, files in os.walk("."):
            # Skip unnecessary directories
            dirs[:] = [
                d
                for d in dirs
                if d not in ["venv", "node_modules", ".git", "__pycache__", "migrations"]
            ]

            for file in files:
                if file.endswith(".py"):
                    file_path = os.path.join(root, file)
                    permissions_found.update(self.scan_python_file(file_path))

        return permissions_found

    def scan_python_file(self, file_path: str) -> Set[str]:
        """Scan a Python file for permission patterns"""
        permissions_found = set()

        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

                # Pattern 1: permission_required decorator
                pattern1 = r'permission_required\(\s*[\'"]([a-z_]+\.[a-z_]+)[\'"]'
                matches = re.findall(pattern1, content)
                permissions_found.update(matches)

                # Pattern 2: user_has_permission function
                pattern2 = r'user_has_permission\([^,]+,\s*[^,]+,\s*[\'"]([a-z_]+\.[a-z_]+)[\'"]'
                matches = re.findall(pattern2, content)
                permissions_found.update(matches)

                # Pattern 3: has_permission function
                pattern3 = r'has_permission\([^,]+,\s*[\'"]([a-z_]+\.[a-z_]+)[\'"]'
                matches = re.findall(pattern3, content)
                permissions_found.update(matches)

                # Pattern 4: Permission.objects.get with code
                pattern4 = r'Permission\.objects\.get\(code\s*=\s*[\'"]([a-z_]+\.[a-z_]+)[\'"]'
                matches = re.findall(pattern4, content)
                permissions_found.update(matches)

                # Pattern 5: check_permission decorator (was missing!)
                pattern5 = r'check_permission\(\s*[\'"]([a-z_]+\.[a-z_]+)[\'"]'
                matches = re.findall(pattern5, content)
                permissions_found.update(matches)

                # Pattern 6: Generic permission string patterns
                # Catches patterns like: permission = "resource.action"
                pattern6 = (
                    r'[\'"]([a-z_]+\.[a-z_]+)[\'"]\s*,?\s*(?:permission|perm_code|required_perm)'
                )
                matches = re.findall(pattern6, content)
                permissions_found.update(matches)

        except Exception as e:
            pass  # Skip files that can't be read

        return permissions_found
