# RBAC Quick Reference Guide for Developers

## TL;DR - How Permissions Work

1. **User** belongs to **Store** via **StoreMembership** with a **Role**
2. **Role** has **Permissions** (can GRANT or DENY)
3. **Store** has **Subscription** to a **Plan** with **Features**
4. **PermissionResolver** checks 5 layers: Plan → Membership → Role → Override → Object
5. **DENY always wins**

---

## Code Snippets

### Function Views

```python
from apps.permissions.decorators import permission_required, feature_required

# Single permission
@permission_required("orders.create")
def create_order(request):
    ...

# With object-level check
@permission_required("orders.update", obj_kwarg="order_id")
def update_order(request, order_id):
    ...

# Feature gating
@feature_required("marketing_campaigns")
def campaign_list(request):
    ...
```

### Class-Based Views

```python
from apps.permissions.mixins import (
    PermissionRequiredMixin,
    FeatureRequiredMixin,
    StoreAccessMixin
)

class OrderCreateView(PermissionRequiredMixin, CreateView):
    permission_required = "orders.create"

class CampaignListView(FeatureRequiredMixin, ListView):
    required_feature = "marketing_campaigns"
```

### DRF ViewSets

```python
from apps.permissions.permissions import (
    HasPermission,
    HasFeature,
    IsStoreMember,
    HasStoreRole
)

class OrderViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStoreMember, HasPermission]
    permission_code = "orders.view"
    object_permission_code = "orders.update"

# With role level requirement
class AdminViewSet(viewsets.ModelViewSet):
    permission_classes = [HasStoreRole.with_level(60)]  # Manager+
```

### In Business Logic

```python
from apps.permissions.services import (
    user_has_permission,
    user_has_feature,
    user_roles_in_store,
    add_member,
    remove_member,
)

# Check permission
if user_has_permission(user, store, "orders.delete"):
    order.delete()

# Check feature
if user_has_feature(user, store, "advanced_reports"):
    generate_advanced_report()

# Get user's roles
roles = user_roles_in_store(user, store)

# Add team member
add_member(new_user, store, manager_role, invited_by=request.user)

# Remove team member
remove_member(user, store, role)
```

### Templates

```django
{% load rbac %}

{# Permission check #}
{% can "orders.create" %}
    <button>Create Order</button>
{% endcan %}

{# Feature check #}
{% has_feature "marketing_campaigns" %}
    <div class="campaign-feature">...</div>
{% endhas %}

{# With object #}
{% can "orders.update" order %}
    <button>Edit</button>
{% endcan %}

{# Multiple permissions #}
{% can_any "orders.create" "orders.update" as can_edit %}
    {% if can_edit %}
        <div class="actions">...</div>
    {% endif %}
{% endcan_any %}
```

---

## Adding New Permissions

### 1. Add to Registry

Edit [`apps/permissions/registry.py`](apps/permissions/registry.py):

```python
RESOURCES = {
    # ... existing resources
    "new_resource": {
        "name": "New Resource",
        "category": "core",
        "description": "...",
        "actions": ["view", "create", "update", "delete"],
    },
}
```

### 2. Run Sync Command

```bash
python manage.py sync_permissions
```

This creates:
- 1 `Resource` row
- N `Permission` rows (one per action)

### 3. Assign to Roles

```python
from apps.permissions.models import Role, Permission, RolePermission

role = Role.objects.get(slug="manager")
permission = Permission.objects.get(code="new_resource.create")

RolePermission.objects.create(
    role=role,
    permission=permission,
    modifier="grant"
)
```

---

## Adding New Features

### 1. Add to Constants

Edit [`apps/permissions/constants.py`](apps/permissions/constants.py):

```python
DEFAULT_FEATURES = (
    # ... existing features
    "new_feature",
)
```

### 2. Add to Plans

Edit [`apps/permissions/seeders/plans_seeder.py`](apps/permissions/seeders/plans_seeder.py):

```python
PLAN_MATRIX = [
    {
        "slug": "growth",
        # ...
        "features": [
            # ... existing
            "new_feature",
        ],
    },
]
```

### 3. Run Seeder

```bash
python manage.py seed_features
python manage.py seed_plans
```

---

## Common Tasks

### Create Custom Role

```python
from apps.permissions.services import clone_role

# Clone from system role
custom_role = clone_role(
    source=Role.objects.get(slug="manager"),
    new_name="Custom Manager",
    new_slug="custom-manager",
    store=current_store
)

# Customize: Add permission
RolePermission.objects.create(
    role=custom_role,
    permission=Permission.objects.get(code="settings.update"),
    modifier="grant"
)

# Customize: Deny permission
RolePermission.objects.create(
    role=custom_role,
    permission=Permission.objects.get(code="employees.delete"),
    modifier="deny"
)
```

### Grant Temporary Access

```python
from apps.permissions.models import UserPermissionOverride
from django.utils import timezone
from datetime import timedelta

# Grant for 24 hours
UserPermissionOverride.objects.create(
    user=user,
    store=store,
    permission=Permission.objects.get(code="reports.export"),
    is_granted=True,
    expires_at=timezone.now() + timedelta(hours=24),
    granted_by=request.user,
    reason="Temporary access for audit"
)
```

### Check Plan Limits

```python
from apps.permissions.services import (
    assert_within_plan_limit,
    plan_limit
)

# Check before adding user
from apps.permissions.models import StoreMembership
current_count = StoreMembership.objects.filter(
    store=store, is_active=True
).count()

try:
    assert_within_plan_limit(store, "max_users", current_count)
    add_member(new_user, store, role)
except PlanLimitExceeded:
    messages.error(request, "Plan limit reached. Upgrade to add more users.")

# Get limit
limit = plan_limit(store, "max_products")  # Returns int or None
```

### Audit Recent Changes

```python
from apps.permissions.models import AuditLog

# Get recent permission changes
recent = AuditLog.objects.filter(
    store=store,
    action__startswith="role."
).order_by("-created_at")[:10]

# Get all changes by a user
user_changes = AuditLog.objects.filter(
    actor=user
).order_by("-created_at")

# Check before/after
for log in AuditLog.objects.filter(target_id=str(role_id)):
    print(f"Action: {log.action}")
    print(f"Before: {log.before}")
    print(f"After: {log.after}")
```

---

## Debugging Permissions

### Check User's Permissions

```python
from apps.permissions.resolver import PermissionResolver

resolver = PermissionResolver()

# Get all grants
grants = resolver.grants(user, store)
print(f"User has {len(grants)} permissions")

# Get all denies
denies = resolver.denies(user, store)
print(f"User is denied {len(denies)} permissions")

# Check specific permission
has_perm = resolver.check(user, store, "orders.create")
print(f"Can create orders: {has_perm}")
```

### Check User's Features

```python
from apps.permissions.services import user_has_feature

for feature in ["customer_management", "marketing_campaigns", "sso"]:
    has = user_has_feature(user, store, feature)
    print(f"{feature}: {has}")
```

### Get User's Roles

```python
from apps.permissions.services import user_roles_in_store

roles = user_roles_in_store(user, store)
for role in roles:
    print(f"- {role.name} (level {role.level})")
```

### Inspect Cache

```bash
# Connect to Redis
redis-cli

# Check user version
GET "rbac:user:123:version"

# Check user permissions
GET "rbac:user:123:s:456:v:1"

# Check store plan version
GET "rbac:store:456:plan_version"
```

### Force Cache Refresh

```python
from apps.permissions.cache import bump_user_version

# Invalidate all caches for this user
bump_user_version(user.id)
```

---

## Testing Permissions

```python
from django.test import TestCase
from apps.permissions.models import StoreMembership, Role

class PermissionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="test@example.com")
        self.store = Store.objects.create(name="Test Store")
        self.role = Role.objects.get(slug="manager")
        
    def test_manager_can_create_orders(self):
        # Arrange
        StoreMembership.objects.create(
            user=self.user,
            store=self.store,
            role=self.role
        )
        
        # Act
        has_perm = user_has_permission(
            self.user, self.store, "orders.create"
        )
        
        # Assert
        self.assertTrue(has_perm)
    
    def test_viewer_cannot_delete_orders(self):
        # Arrange
        viewer_role = Role.objects.get(slug="viewer")
        StoreMembership.objects.create(
            user=self.user,
            store=self.store,
            role=viewer_role
        )
        
        # Act
        has_perm = user_has_permission(
            self.user, self.store, "orders.delete"
        )
        
        # Assert
        self.assertFalse(has_perm)
```

---

## Important Notes

### DENY is Absolute

```python
# Role grants "orders.delete"
# Override denies "orders.delete"
# Result: DENY wins (user cannot delete)
```

### Superuser Bypass

```python
# Superusers pass all permission checks
# This is auditable but not enforced by resolver
if user.is_superuser:
    return True  # Always allowed
```

### Store Must Be Set

```python
# Permission checks fail without store
# Always ensure request.store is set
# Via session, middleware, or explicit assignment
```

### Membership Must Be Active

```python
# Inactive or expired memberships = no permissions
# Check: is_active=True AND (expires_at IS NULL OR expires_at > now)
```

### Subscription Must Be Active

```python
# Feature checks fail if subscription is not active
# Active means: status='active' OR status='trialing' AND not expired
```

---

## File Locations

| What You Need | Where to Find It |
|---------------|-----------------|
| Add permission | [`apps/permissions/registry.py`](apps/permissions/registry.py) |
| Add feature | [`apps/permissions/constants.py`](apps/permissions/constants.py), [`apps/permissions/seeders/plans_seeder.py`](apps/permissions/seeders/plans_seeder.py) |
| Use decorator | [`apps/permissions/decorators.py`](apps/permissions/decorators.py) |
| Use mixin | [`apps/permissions/mixins.py`](apps/permissions/mixins.py) |
| Use DRF permission | [`apps/permissions/permissions.py`](apps/permissions/permissions.py) |
| Check in code | [`apps/permissions/services.py`](apps/permissions/services.py) |
| Template tag | [`apps/permissions/templatetags/rbac.py`](apps/permissions/templatetags/rbac.py) |
| Cache utilities | [`apps/permissions/cache.py`](apps/permissions/cache.py) |
| Signal handlers | [`apps/permissions/signals.py`](apps/permissions/signals.py) |

---

## Command Reference

```bash
# Sync permissions from registry to database
python manage.py sync_permissions

# Seed system roles
python manage.py seed_roles

# Seed features
python manage.py seed_features

# Seed subscription plans
python manage.py seed_plans

# Seed all (roles, features, plans)
python manage.py seed_all

# Export audit log
python manage.py export_audit_log --store-id=<id> --output-file=audit.csv
```
