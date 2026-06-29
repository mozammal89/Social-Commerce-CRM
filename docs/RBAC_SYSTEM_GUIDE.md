# RBAC System - Complete Guide

## 📚 Table of Contents

1. [System Overview](#system-overview)
2. [Architecture](#architecture)
3. [Quick Start](#quick-start)
4. [Development Workflow](#development-workflow)
5. [Sync Process](#sync-process)
6. [Troubleshooting](#troubleshooting)
7. [Best Practices](#best-practices)

---

## 🎯 System Overview

### **What is RBAC?**
Role-Based Access Control (RBAC) manages user permissions through roles instead of individual user assignments.

### **Core Components:**

```
User → Role → Permission → Action on Resource
```

**Example:**
```
John Doe → Manager Role → customers.delete → Delete Customers
```

### **Permission Format:**
```
<resource>.<action>

Examples:
- customers.view     # View customer list
- orders.create      # Create new order
- dashboard.view     # Access dashboard
- roles.manage       # Manage system roles
```

---

## 🏗️ Architecture

### **Database Models:**

#### **1. Resource**
- **code**: Unique identifier (e.g., "customers")
- **name**: Display name (e.g., "Customers")
- **category**: Group (e.g., "sales", "admin", "marketing")
- **actions**: List of allowed actions (["view", "create", "update", "delete"])

#### **2. Permission**
- **code**: Auto-generated `<resource>.<action>` (e.g., "customers.delete")
- **resource**: ForeignKey to Resource
- **action**: Action name (e.g., "delete")

#### **3. Role**
- **name**: Display name (e.g., "Manager")
- **slug**: Machine-friendly name (e.g., "manager")
- **store**: NULL for system roles, set for custom roles

#### **4. RolePermission**
- **role**: ForeignKey to Role
- **permission**: ForeignKey to Permission
- **modifier**: "grant", "deny", or "default"

### **System Roles:**
- `store-owner`: Full access (*)
- `admin`: Administrative access (*)
- `manager`: Business operations
- `sales-agent`: Sales activities
- `customer-support`: Customer service
- `inventory-manager`: Inventory control
- `marketing-executive`: Marketing campaigns
- `accountant`: Financial reports
- `viewer`: Read-only access

---

## 🚀 Quick Start

### **Initial Setup:**

```bash
# 1. Run all permission seeders
python manage.py seed resources roles role-permissions

# 2. Verify setup
python manage.py shell
```

```python
from apps.permissions.models import Resource, Permission, Role
from apps.permissions.services import user_has_permission

# Check system state
print(f"Resources: {Resource.objects.count()}")       # Should be 18
print(f"Permissions: {Permission.objects.count()}")   # Should be 59
print(f"System Roles: {Role.objects.filter(store=None).count()}")  # Should be 9

# Test permission check
user = User.objects.first()
store = Store.objects.first()
has_perm = user_has_permission(user, store, "customers.view")
print(f"Has permission: {has_perm}")
```

---

## 🛠️ Development Workflow

### **Adding New Views with Permissions:**

#### **Step 1: Define the Permission**

**File:** `apps/dashboard/views.py`

```python
from django.contrib.auth.decorators import permission_required
from apps.permissions.decorators import check_permission

# Using decorator (recommended)
@permission_required("analytics.advanced_reports", raise_exception=True)
def advanced_analytics_view(request):
    return render(request, 'analytics/advanced.html')

# Using function-based permission check
def sensitive_data_view(request):
    if not user_has_permission(request.user, request.store, "reports.export"):
        raise PermissionDenied("You don't have permission to export reports")
    # ... view logic
```

#### **Step 2: Add Permission to Seeder (Manual)**

**File:** `apps/permissions/seeders/permissions_seeder.py`

```python
ROLE_PERMISSION_MATRIX: dict[str, set[str]] = {
    "manager": {
        # ... existing permissions
        "analytics.advanced_reports",  # Add new permission
        "reports.export",
    },
    "accountant": {
        # ... existing permissions
        "analytics.advanced_reports",  # Add new permission
        "reports.export",
    },
}
```

#### **Step 3: Add Resource to Seeder (If New Resource)**

**File:** `apps/permissions/seeders/resources_seeder.py`

```python
RESOURCE_CATALOG = [
    # ... existing resources
    ("analytics", "Analytics", "analytics", ["view", "advanced_reports", "export"]),
]
```

#### **Step 4: Run Seeders to Update Database**

```bash
# Update resources first (if new resource)
python manage.py seed resources

# Then update role permissions
python manage.py seed role-permissions

# Or run both together
python manage.py seed resources role-permissions
```

---

## 🔄 Sync Process

### **When to Sync:**

1. ✅ **After adding new views** with permission requirements
2. ✅ **After modifying existing permissions** in seeders
3. ✅ **After deployment** to staging/production
4. ✅ **After permission code changes** in constants

### **Sync Commands:**

#### **Option 1: Manual Sync (Production)**

```bash
# Step 1: Scan for new permissions in codebase
python scripts/comprehensive_permission_update.py

# Step 2: Review the generated changes
# Check: apps/permissions/seeders/permissions_seeder.py
# Check: apps/permissions/seeders/resources_seeder.py

# Step 3: Run seeders to apply changes
python manage.py seed resources role-permissions

# Step 4: Verify sync
python manage.py shell
```

```python
from apps.permissions.models import Resource, Permission
print(f"Resources: {Resource.objects.count()}")
print(f"Permissions: {Permission.objects.count()}")
```

#### **Option 2: Auto-Sync (Development)**

```bash
# One command to scan, update, and sync
python manage.py permission --sync

# With verbose output
python manage.py permission --sync --verbose

# Dry run (preview changes only)
python manage.py permission --sync --dry-run
```

#### **Option 3: Interactive Sync (Recommended)**

```bash
# Interactive mode with prompts
python manage.py permission --interactive

# This will:
# 1. Scan for new permissions
# 2. Show you what's missing
# 3. Ask for confirmation
# 4. Update seeders
# 5. Apply changes
```

### **Sync Verification:**

```bash
# List all current permissions
python manage.py permission --list

# Show gaps between code and database
python manage.py permission --audit

# Test specific permission
python manage.py permission --test "customers.delete"
```

---

## 🧪 Complete Example: Adding New Feature

### **Scenario:** Add "Advanced Analytics" feature with export capability

#### **Step 1: Create View with Permission**

**File:** `apps/analytics/views.py`

```python
from django.shortcuts import render
from django.contrib.auth.decorators import permission_required
from apps.permissions.decorators import check_permission

@permission_required("analytics.advanced_reports", raise_exception=True)
def advanced_analytics(request):
    data = get_advanced_analytics_data(request.store)
    return render(request, 'analytics/advanced.html', {'data': data})

@check_permission("analytics.export", raise_exception=True)
def export_analytics(request):
    export_data = generate_analytics_export(request.store)
    return export_data.as_csv_response()
```

#### **Step 2: Add URL Pattern**

**File:** `apps/analytics/urls.py`

```python
from django.urls import path
from .views import advanced_analytics, export_analytics

urlpatterns = [
    path('analytics/advanced/', advanced_analytics, name='advanced_analytics'),
    path('analytics/export/', export_analytics, name='export_analytics'),
]
```

#### **Step 3: Sync Permissions**

```bash
# Option A: Automatic sync (recommended)
python manage.py permission --interactive

# Option B: Manual sync
python scripts/comprehensive_permission_update.py
python manage.py seed resources role-permissions
```

#### **Step 4: Verify Permissions**

```bash
# Test with a user
python manage.py permission --test "analytics.advanced_reports"
python manage.py permission --test "analytics.export"

# Check which roles have access
python manage.py permission --show-roles "analytics.advanced_reports"
```

---

## 🐛 Troubleshooting

### **Common Issues:**

#### **Issue 1: Permission Not Found**

```python
# Error: Permission.DoesNotExist
# Solution: Run sync to create missing permissions
python manage.py permission --sync
```

#### **Issue 2: Seeder Conflicts**

```bash
# Error: Duplicate key violation
# Solution: Clear and reseed (dev environment only)
python manage.py seed --flush
python manage.py seed resources role-permissions
```

#### **Issue 3: Permission Not Working**

```bash
# Check if user has role
python manage.py shell
```

```python
from apps.permissions.models import Role, RolePermission

user = User.objects.get(email='user@example.com')
role = Role.objects.get(slug='manager')

# Check user has role
user_roles = user.roles.filter(store=user.store)
print(f"User roles: {[r.slug for r in user_roles]}")

# Check role has permission
permissions = role.role_permissions.filter(modifier='grant')
print(f"Role permissions: {[p.permission.code for p in permissions]}")
```

#### **Issue 4: Seeder Not Found**

```bash
# List available seeders
python manage.py seed --list

# If 'resources' not listed, check registration
# File: apps/core/seeders/__init__.py
```

---

## 📋 Best Practices

### **1. Permission Naming Convention**

```
<resource>.<action>

Good:
- customers.view
- orders.create
- analytics.advanced_reports
- roles.manage_system

Bad:
- viewCustomers
- create_order
- analyticsAdvancedReports
- manageSystemRoles
```

### **2. Resource Categorization**

```python
# Use standard categories
categories = [
    "admin",      # RBAC, audit, system
    "sales",      # customers, orders, returns
    "marketing",  # campaigns, promotions
    "inventory",  # products, warehouses
    "analytics",  # reports, dashboards
    "operations", # general operations
]
```

### **3. Action Standards**

```python
# Standard actions per resource type
read_only = ["view"]
crud = ["view", "create", "update", "delete"]
enhanced = ["view", "create", "update", "delete", "export", "import"]
special = ["view", "create", "update", "delete", "export", "approve", "manage"]
```

### **4. Development vs Production**

```python
# Development: Auto-create permissions for quick iteration
if settings.DEBUG:
    user_has_permission(user, store, code, auto_create=True)

# Production: Only allow seeded permissions
if not settings.DEBUG:
    user_has_permission(user, store, code, auto_create=False)
```

### **5. Testing Permissions**

```python
# Always test permission checks in unit tests
from django.test import TestCase, override_settings
from apps.permissions.services import user_has_permission

class PermissionTests(TestCase):
    def test_manager_can_delete_customers(self):
        manager = create_user_with_role('manager')
        store = create_store()
        self.assertTrue(user_has_permission(manager, store, "customers.delete"))
        
    def test_viewer_cannot_delete_customers(self):
        viewer = create_user_with_role('viewer')
        store = create_store()
        self.assertFalse(user_has_permission(viewer, store, "customers.delete"))
```

---

## 📞 Support & Commands Reference

### **Available Commands:**

```bash
# Permission management
python manage.py permission --help
python manage.py permission --list
python manage.py permission --sync
python manage.py permission --audit
python manage.py permission --test <permission_code>
python manage.py permission --show-roles <permission_code>

# Seeder management
python manage.py seed --help
python manage.py seed --list
python manage.py seed resources
python manage.py seed roles
python manage.py seed role-permissions
python manage.py seed --flush  # Dev only!
```

### **Quick Reference:**

| Command | Purpose |
|---------|---------|
| `python manage.py permission --sync` | Sync all permissions |
| `python manage.py permission --audit` | Find permission gaps |
| `python manage.py seed resources` | Create/Update resources |
| `python manage.py seed role-permissions` | Update role permissions |
| `python scripts/comprehensive_permission_update.py` | Scan and update seeders |

---

## 🎯 Summary

### **Workflow Recap:**

1. **Add View** → `@permission_required("resource.action")`
2. **Sync Permissions** → `python manage.py permission --sync`
3. **Run Seeders** → `python manage.py seed resources role-permissions`
4. **Verify** → `python manage.py permission --test "resource.action"`

### **Key Points:**

✅ **Always sync after adding new permissions**
✅ **Use standard naming conventions**
✅ **Test permission checks in development**
✅ **Run seeders in correct order** (resources → roles → permissions)
✅ **Use interactive sync** to review changes before applying
✅ **Document custom permissions** for team reference

---

**Last Updated:** 2026-06-29
**RBAC Version:** 2.0
**Supported Django:** 4.2+