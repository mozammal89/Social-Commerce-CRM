# 🔄 RBAC System Sync - Complete Step-by-Step Guide

## 🎯 Purpose
This guide shows you exactly how to add new views with permissions and sync the RBAC system using real examples from the demo app.

---

## 📋 What We'll Do

### **Scenario**: We created 8 new demo views with 5 NEW permissions:
1. `analytics.advanced_reports` - Advanced analytics dashboard
2. `analytics.export` - Export analytics data  
3. `analytics.live_data` - Real-time dashboard updates
4. `system.manage_integrations` - Manage third-party integrations
5. `customers.bulk_operations` - Bulk customer operations

**These permissions DON'T exist in our system yet!**

---

## 🔧 Step-by-Step Sync Process

### **STEP 1: Audit Current State** 🔍
Check what permissions exist vs what's needed.

```bash
# Run permission audit to find gaps
python manage.py permission --audit
```

**Expected Output:**
```
================================================================================
RBAC SYSTEM AUDIT
================================================================================

📊 AUDIT RESULTS:

1️⃣ PERMISSION GAPS:
   5 permissions in code but not in database:
      - analytics.advanced_reports
      - analytics.export  
      - analytics.live_data
      - system.manage_integrations
      - customers.bulk_operations

2️⃣ EXTRA PERMISSIONS:
   ✓ No extra permissions

3️⃣ UNASSIGNED PERMISSIONS:
   ✓ All permissions are assigned

📋 SUMMARY:
   Codebase permissions: 64
   Database permissions: 59
   Issues found: 5
```

---

### **STEP 2: Interactive Sync** 🤝
Let the system guide you through adding missing permissions.

```bash
# Interactive mode - shows what will change and asks for confirmation
python manage.py permission --sync --interactive
```

**Expected Output:**
```
================================================================================
PERMISSION SYNC - CODEBASE → DATABASE  
================================================================================

🔍 Step 1: Scanning codebase for permissions...
   Found 64 permissions in codebase
      - analytics.advanced_reports
      - analytics.export
      - analytics.live_data
      - system.manage_integrations
      - customers.bulk_operations
      - (and 59 existing permissions)

🗄️ Step 2: Getting current database permissions...
   Found 59 permissions in database

📊 Step 3: Analyzing differences...
   Missing in database: 5
   Extra in database: 0

📋 SYNC SUMMARY:
   Codebase permissions: 64
   Database permissions: 59  
   Missing to add: 5

   Missing permissions:
      - analytics.advanced_reports
      - analytics.export
      - analytics.live_data
      - system.manage_integrations
      - customers.bulk_operations

❓ Do you want to proceed with sync? (yes/no)
> yes
```

---

### **STEP 3: Confirm and Sync** ✅
The system creates the missing permissions.

**Expected Output (after confirmation):**
```
🔧 Adding 5 missing permissions...
      ✓ Added: analytics.advanced_reports
      ✓ Added: analytics.export
      ✓ Added: analytics.live_data
      ✓ Added: system.manage_integrations
      ✓ Added: customers.bulk_operations

✅ Added 5 permissions to database

================================================================================
SYNC COMPLETE
================================================================================

📊 Final database state:
   Resources: 20
   Permissions: 64
```

---

### **STEP 4: Verify Sync** ✅
Check that permissions were created correctly.

```bash
# List all permissions to verify
python manage.py permission --list | grep analytics
```

**Expected Output:**
```
📋 analytics.advanced_reports
   Resource: Analytics (analytics)
   Action: advanced_reports
   ✅ Granted to: store-owner, admin, manager
   ❌ Denied to: sales-agent, customer-support, inventory-manager, marketing-executive, accountant, viewer

📋 analytics.export  
   Resource: Analytics (analytics)
   Action: export
   ✅ Granted to: store-owner, admin, manager, accountant
   ❌ Denied to: sales-agent, customer-support, inventory-manager, marketing-executive, viewer
```

---

### **STEP 5: Test Permissions** 🧪
Test if the permissions work with actual users.

```bash
# Test specific permission
python manage.py permission --test "analytics.advanced_reports"
```

**Expected Output:**
```
================================================================================
TESTING PERMISSION: analytics.advanced_reports
================================================================================
✓ Permission exists in database
   Resource: Analytics
   Action: advanced_reports

📋 ROLE ASSIGNMENTS:
   ✅ Store Owner (GRANT)
   ✅ Admin (GRANT) 
   ✅ Manager (GRANT)
   ❌ Sales Agent (DENY)
   ❌ Viewer (DENY)

👥 USER TESTING:
   ✅ admin@example.com (Admin)
   ✅ manager@example.com (Manager)
   ❌ salesagent@example.com (Sales Agent)
   ❌ viewer@example.com (Viewer)
```

---

## 🆕 Alternative: Manual Sync Process

If you prefer manual control, here's the traditional approach:

### **STEP 1: Manual Seeder Update**
Edit `apps/permissions/seeders/resources_seeder.py`:

```python
RESOURCE_CATALOG = [
    # ... existing resources
    ("analytics", "Analytics", "analytics", 
     ["view", "advanced_reports", "export", "live_data"]),
    ("system", "System", "admin", 
     ["manage_integrations"]),
    ("customers", "Customers", "sales", 
     ["view", "create", "update", "delete", "export", "bulk_operations"]),
]
```

### **STEP 2: Update Role Matrix**
Edit `apps/permissions/seeders/permissions_seeder.py`:

```python
ROLE_PERMISSION_MATRIX: dict[str, set[str]] = {
    "manager": {
        # ... existing permissions
        "analytics.advanced_reports",
        "analytics.export",
    },
    "admin": {
        # ... existing permissions (has "*" so gets everything)
    },
    "accountant": {
        # ... existing permissions
        "analytics.export",
    },
}
```

### **STEP 3: Run Seeders**
```bash
# Run resource seeder first
python manage.py seed resources

# Then role-permissions seeder
python manage.py seed role-permissions
```

### **STEP 4: Verify**
```bash
python manage.py permission --test "analytics.advanced_reports"
```

---

## 🚀 Quick Command Reference

### **Daily Development Workflow:**

```bash
# After adding new views with permissions:
python manage.py permission --audit              # Check for gaps
python manage.py permission --sync --interactive # Sync interactively
python manage.py permission --test "new.perm"    # Test specific permission
```

### **Production Deployment:**

```bash
# Review changes before deploying
python manage.py permission --audit
python manage.py permission --sync --dry-run     # Preview only

# Then apply changes
python manage.py permission --sync

# Final verification
python manage.py permission --list
python manage.py permission --test "critical.perm"
```

### **Troubleshooting:**

```bash
# Find which roles have a permission
python manage.py permission --show-roles "analytics.export"

# List all permissions
python manage.py permission --list

# Check permission for specific user
python manage.py shell
```

```python
from apps.permissions.services import user_has_permission
user = User.objects.get(email='user@example.com')
store = Store.objects.first()
result = user_has_permission(user, store, "analytics.advanced_reports")
print(f"Has permission: {result}")
```

---

## 🧪 Testing the Demo Views

### **1. Test Advanced Analytics View**
```bash
# Visit: /demo/advanced-analytics/
# Required permission: analytics.advanced_reports
```

**Expected Behavior:**
- ✅ **Admin/Manager**: Can access the view
- ❌ **Sales Agent/Viewer**: Gets "Permission Denied"

### **2. Test Permission Test View** 
```bash
# Visit: /demo/permission-test/
# Shows all permissions and whether current user has them
```

**Expected Output:**
```json
{
  "title": "Permission Test Dashboard",
  "user": "admin@example.com",
  "results": {
    "customers.view": true,
    "analytics.advanced_reports": true,
    "analytics.export": true,
    "system.manage_integrations": true,
    "customers.bulk_operations": false
  },
  "statistics": {
    "total": 5,
    "granted": 4,
    "denied": 1
  }
}
```

### **3. Test API Endpoints**
```bash
# Test API with permission
curl -H "Authorization: Bearer <token>" \
     http://localhost:8000/api/analytics/summary/

# Expected: 200 OK if user has analytics.advanced_reports
# Expected: 403 Forbidden if user doesn't have permission
```

---

## 📊 Sync Process Comparison

| Method | Pros | Cons | Best For |
|--------|------|------|----------|
| **Interactive Sync** | ✅ Safe, guided, ✅ Auto-scans code, ✅ No manual editing | ⚠️ Requires confirmation | Daily development |
| **Auto Sync** | ✅ Fast, ✅ One command, ✅ No prompts | ⚠️ Less control, ⚠️ Might create unwanted permissions | CI/CD pipelines |
| **Manual Sync** | ✅ Full control, ✅ Review before apply | ❌ Slow, ❌ Error-prone, ❌ Requires manual updates | Production deployments |
| **Dry Run** | ✅ Preview changes, ✅ Safe to test | ❌ Doesn't apply changes | Pre-deployment checks |

---

## 🎯 Summary: Complete Workflow

### **Option 1: Recommended Workflow (Interactive)**
```bash
# 1. Add new views with permissions
# 2. Audit for gaps
python manage.py permission --audit

# 3. Interactive sync (recommended)
python manage.py permission --sync --interactive

# 4. Verify
python manage.py permission --test "new.permission"

# 5. Test the view
# Visit /demo/advanced-analytics/
```

### **Option 2: Quick Workflow (Auto)**
```bash
# 1. Add new views with permissions  
# 2. Auto sync (fast)
python manage.py permission --sync

# 3. Test
python manage.py permission --test "new.permission"
```

### **Option 3: Production Workflow (Manual)**
```bash
# 1. Add new views with permissions
# 2. Update seeders manually
# 3. Dry run to preview
python manage.py permission --sync --dry-run

# 4. Run seeders
python manage.py seed resources role-permissions

# 5. Verify thoroughly
python manage.py permission --audit
python manage.py permission --list
```

---

## 🚨 Important Notes

### **Security Considerations:**
- ✅ **Interactive mode** is safest - shows what will change
- ⚠️ **Auto sync** can create unwanted permissions 
- ✅ **Always test** permissions in development first
- ✅ **Review role assignments** after sync

### **Development vs Production:**
- **Development**: Use `--interactive` or auto-sync
- **Staging**: Use `--dry-run` first, then sync
- **Production**: Use manual seeder updates with code review

### **Backup Recommendations:**
```bash
# Backup before major permission changes
python manage.py dumpdata permissions > backup_permissions.json

# Restore if needed
python manage.py loaddata backup_permissions.json
```

---

## 📞 Quick Help

### **View All Commands:**
```bash
python manage.py permission --help
python manage.py seed --help
```

### **Check Current State:**
```bash
python manage.py permission --list    # All permissions
python manage.py permission --audit   # System health
python manage.py seed --list          # Available seeders
```

### **Test Specific Permission:**
```bash
python manage.py permission --test "analytics.advanced_reports"
python manage.py permission --show-roles "analytics.export"
```

---

**That's it!** You now have a complete RBAC sync workflow with real examples. The interactive sync command is the recommended approach for most scenarios. 🎉