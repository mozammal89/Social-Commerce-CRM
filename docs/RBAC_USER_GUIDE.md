# Roles & Permissions — End-to-End User Guide

A practical walkthrough of how the authorization system works and how to
make it do what you want.

This guide is written for **two audiences**:

1. **Developers** wiring permission checks into views, templates, and APIs.
2. **Operators / store admins** managing roles and members through Django
   admin and the shell.

If you read this top-to-bottom, you should be able to do anything the
system supports.

---

## Table of Contents

1. [The mental model in 60 seconds](#1-the-mental-model-in-60-seconds)
2. [The five layers, explained](#2-the-five-layers-explained)
3. [What ships out of the box](#3-what-ships-out-of-the-box)
4. [First-time setup](#4-first-time-setup)
5. [Everyday workflows](#5-everyday-workflows)
6. [Recipes for common tasks](#6-recipes-for-common-tasks)
7. [Adding a new permission](#7-adding-a-new-permission)
8. [Adding a new role](#8-adding-a-new-role)
9. [Adding a new plan / feature](#9-adding-a-new-plan--feature)
10. [Wiring permission checks into your code](#10-wiring-permission-checks-into-your-code)
11. [Templates, DRF, and JWT — at a glance](#11-templates-drf-and-jwt--at-a-glance)
12. [Caching and invalidation](#12-caching-and-invalidation)
13. [Audit log](#13-audit-log)
14. [Troubleshooting](#14-troubleshooting)

---

## 1. The mental model in 60 seconds

A user can do something in a store **only if all of these are true**:

1. Their **store's subscription plan** includes the relevant feature
   (e.g. "marketing campaigns").
2. They are an **active member** of that store.
3. Their **role** in that store grants the relevant permission.
4. They have **no DENY override** for that permission.
5. (If it's about a specific object) the **object-level rule** lets them.

That's it. Five layers, top-to-bottom, deny-at-any-layer short-circuits.

The system knows about **permissions** like `orders.create`, `customers.view`,
`reports.export`. It does NOT know about your app's domain logic ("a sales
agent can only see their own orders") — that's the **object-level** layer,
where you write a small Python function that decides.

Everything else (roles, plans, memberships) is just bookkeeping to decide
which permission codes are granted.

---

## 2. The five layers, explained

```
┌──────────────────────────────────────────────────────────────────┐
│ Layer 1 — Subscription Feature                                   │
│   Does this store's plan include <feature>?                      │
│   Fails → 402 (upgrade page in HTML, 402 in API)                 │
├──────────────────────────────────────────────────────────────────┤
│ Layer 2 — Store Membership                                       │
│   Is the user an ACTIVE member of this store?                    │
│   Fails → 403                                                    │
├──────────────────────────────────────────────────────────────────┤
│ Layer 3 — Role Permissions                                       │
│   Does any of the user's roles in this store GRANT <permission>? │
│   DENY beats GRANT.                                              │
├──────────────────────────────────────────────────────────────────┤
│ Layer 4 — User Override                                          │
│   Is there an explicit user-level grant/deny for <permission>?   │
│   DENY is absolute.                                              │
├──────────────────────────────────────────────────────────────────┤
│ Layer 5 — Object-level (optional, per-resource)                  │
│   Run a registered Python function with the actual object.       │
│   Default: pass-through.                                         │
└──────────────────────────────────────────────────────────────────┘
```

### The "DENY wins" rule

If a Manager role grants `orders.approve` and a Viewer role denies
`orders.approve`, and the user has both roles → **DENY wins**.

This prevents accidental privilege escalation. If a manager leaks an
invite to someone in Viewer, the Viewer-level DENY blocks them from
escalating.

### Stable permission codes

Permission codes look like `customers.view`, `orders.create`. They are
**stable strings** — never rename them in production without a migration,
because JWT tokens, audit logs, and DB rows all reference them by code.

---

## 3. What ships out of the box

### Resources (18)

| Code | What it is |
|---|---|
| `dashboard` | Home widgets |
| `customers`, `customer_groups` | CRM records |
| `products`, `categories`, `inventory`, `warehouses` | Catalog |
| `orders`, `returns`, `couriers` | Sales |
| `campaigns`, `promo_codes` | Marketing |
| `reports` | Analytics |
| `employees`, `roles`, `permissions` | Team management |
| `integrations`, `settings` | Platform |

### Actions (9)

`view`, `create`, `update`, `delete`, `export`, `import`, `approve`, `assign`, `manage` (wildcard).

### System roles (9)

| Slug | Level | What it gets |
|---|---|---|
| `store-owner` | 100 | Everything (wildcard) |
| `admin` | 80 | Everything (wildcard) |
| `manager` | 60 | Day-to-day ops: customers, orders, products, reports |
| `sales-agent` | 40 | Customers + own orders |
| `customer-support` | 35 | Read + reply on customers/orders, returns |
| `inventory-manager` | 40 | Stock, warehouses, products |
| `marketing-executive` | 40 | Campaigns + promo codes + customer groups |
| `accountant` | 40 | Orders (read/export) + reports |
| `viewer` | 20 | Read-only across the store |

### Plans (4)

| Plan | Price | Users | Stores | Notable features |
|---|---|---|---|---|
| Starter | $19 | 3 | 1 | customer_management, basic_reports |
| Growth | $49 | 10 | 3 | + marketing_campaigns, advanced_reports, inventory |
| Professional | $99 | 25 | 10 | + multi_warehouse, api_access, FB/WA |
| Enterprise | $299 | ∞ | ∞ | + SSO, audit_export |

---

## 4. First-time setup

You only need to do this once per environment.

```bash
# 1. Apply all migrations (creates RBAC tables)
python manage.py migrate

# 2. Sync the permission registry → DB
python manage.py sync_permissions

# 3. Seed the default roles, plans, and role-permission matrix
python manage.py seed roles
python manage.py seed plans
python manage.py seed role-permissions

# 4. If you have legacy Store.owners/managers/staff M2Ms, migrate them
python manage.py migrate permissions 0002_migrate_legacy_memberships
```

That's it. You now have 18 resources, 75 permissions, 9 roles, 4 plans
in the database.

### CI gate

Add this to your CI pipeline to catch registry drift:

```bash
python manage.py sync_permissions --check
# Exit 0 = in sync, exit 1 = drift detected
```

---

## 5. Everyday workflows

### A. Add a member to a store

**Via Django admin:**

1. Go to `/admin/permissions/storemembership/`
2. Click "Add store membership"
3. Pick the user, the store, and the role
4. Check "Active"
5. Save

**Via Python shell:**

```python
python manage.py shell

from apps.permissions.models import StoreMembership, Role
from apps.stores.models import Store
from apps.accounts.models import User

user = User.objects.get(email="alice@example.com")
store = Store.objects.get(name="Tech Haven")
role = Role.objects.get(slug="manager")

StoreMembership.objects.create(
    user=user, store=store, role=role, is_active=True,
)
```

The cache will be invalidated automatically by the post_save signal — Alice's
next request will see her new permissions immediately.

### B. Change a member's role

```python
membership = StoreMembership.objects.get(user=user, store=store, role=old_role)
membership.role = Role.objects.get(slug="manager")
membership.save()
```

### C. Remove a member

Soft-deactivate (keeps the audit trail):

```python
StoreMembership.objects.filter(user=user, store=store).update(is_active=False)
```

Hard-delete (loses audit trail):

```python
StoreMembership.objects.filter(user=user, store=store).delete()
```

### D. Make a user a Store Owner

```python
StoreMembership.objects.update_or_create(
    user=user, store=store,
    defaults={"role": Role.objects.get(slug="store-owner"), "is_active": True},
)
```

### E. Grant one user an extra permission

```python
from apps.permissions.models import UserPermissionOverride, Permission

UserPermissionOverride.objects.create(
    user=user, store=store,
    permission=Permission.objects.get(code="reports.export"),
    is_granted=True,
    reason="Q1 audit assist",
    granted_by=request.user,
)
```

### F. Explicitly deny one user a permission

```python
UserPermissionOverride.objects.create(
    user=user, store=store,
    permission=Permission.objects.get(code="orders.delete"),
    is_granted=False,   # DENY is absolute
    reason="Pending investigation",
    granted_by=request.user,
)
```

### G. Time-box a grant

```python
from django.utils import timezone
UserPermissionOverride.objects.create(
    user=user, store=store,
    permission=Permission.objects.get(code="campaigns.approve"),
    is_granted=True,
    expires_at=timezone.now() + timezone.timedelta(days=7),
)
```

---

## 6. Recipes for common tasks

### "Block everyone from deleting orders during the holiday freeze"

Use a **DENY override on the Viewer role** (or any role that might
otherwise have delete):

```python
RolePermission.objects.update_or_create(
    role=Role.objects.get(slug="viewer"),
    permission=Permission.objects.get(code="orders.delete"),
    defaults={"modifier": "deny"},
)
```

To restore later, set the modifier back to `grant` or remove the row.

### "Promote this user to Manager for just one store"

```python
StoreMembership.objects.update_or_create(
    user=user, store=specific_store,
    defaults={"role": Role.objects.get(slug="manager"), "is_active": True},
)
```

### "Audit which roles grant `orders.delete`"

```python
from apps.permissions.models import RolePermission

RolePermission.objects.filter(
    permission__code="orders.delete",
    modifier="grant",
).select_related("role").values_list("role__slug", flat=True)
# → ['store-owner', 'admin']
```

### "List all permissions a user has in a store"

```python
from apps.permissions.resolver import PermissionResolver

grants, denies = PermissionResolver()._compute_grants_and_denies(user, store)
print("GRANTS:", sorted(grants))
print("DENIES:", sorted(denies))
```

### "Check if a user can do X right now"

```python
from apps.permissions.services import user_has_permission

if user_has_permission(user, store, "orders.create"):
    # show the button
```

### "Check if a user's store plan has feature X"

```python
from apps.permissions.services import store_has_feature, user_has_feature

if store_has_feature(store, "marketing_campaigns"):
    # show the campaigns tab
if user_has_feature(user, store, "marketing_campaigns"):
    # the user is also a member, so they can use it
```

---

## 7. Adding a new permission

You only do this when adding a brand-new resource or a new action to an
existing one.

**Step 1.** Edit `apps/permissions/registry.py` and add an entry:

```python
RESOURCES = {
    ...
    "invoices": {
        "name": "Invoices",
        "category": "billing",
        "actions": ["view", "create", "export"],
    },
}
```

**Step 2.** Sync the DB:

```bash
python manage.py sync_permissions
```

This adds a `Resource(invoices, ...)` row and 3 `Permission` rows
(`invoices.view`, `invoices.create`, `invoices.export`). Idempotent — safe
to run on every deploy.

**Step 3.** Bind it to roles in `apps/permissions/seeders/permissions_seeder.py`:

```python
ROLE_PERMISSION_MATRIX = {
    ...
    "accountant": {
        ...
        "invoices.view", "invoices.create", "invoices.export",
    },
}
```

**Step 4.** Re-run the seeder:

```bash
python manage.py seed role-permissions
```

**Step 5.** Use it in code:

```python
@permission_required("invoices.export")
def export_invoices(request):
    ...
```

### Adding a new action verb

Edit `apps/permissions/constants.py`:

```python
ACTIONS = (
    "view", "create", "update", "delete",
    "export", "import", "approve", "assign",
    "manage",
    "archive",  # new
)
```

Then add it to the `actions` list of any resource that should support it,
and re-run `sync_permissions`.

---

## 8. Adding a new role

### A. Add a new system role

**Step 1.** Add it to `apps/permissions/seeders/roles_seeder.py`:

```python
SYSTEM_ROLES = [
    ...
    ("refund-approver", "Refund Approver", 50,
     "Can approve returns and refunds."),
]
```

**Step 2.** Add it to `apps/permissions/constants.py`:

```python
DEFAULT_ROLES = (
    ...,
    "refund-approver",
)
```

**Step 3.** Bind permissions in `permissions_seeder.py`:

```python
ROLE_PERMISSION_MATRIX = {
    ...
    "refund-approver": {
        "dashboard.view",
        "returns.view", "returns.approve",
        "orders.view",
    },
}
```

**Step 4.** Run the seeders:

```bash
python manage.py seed roles
python manage.py seed role-permissions
```

### B. Create a custom role for ONE store

Custom roles are per-store. Use the admin UI at `/admin/permissions/role/`:

- Click "Add role"
- **Leave `Store` empty** for system roles
- **Pick a store** for custom roles
- Tick "Active"
- Save

Then bind permissions in the role's "Role permissions" inline.

### C. Clone a role

```python
from apps.permissions.services import clone_role

source = Role.objects.get(slug="manager")
new_role = clone_role(
    source,
    new_name="Junior Manager",
    new_slug="junior-manager",
)
```

The clone inherits all `RolePermission` rows from the source. Modify the
clone afterwards to tweak permissions for this specific store.

---

## 9. Adding a new plan / feature

### A. Add a new feature

Edit `apps/permissions/seeders/features_seeder.py` (or seed directly):

```python
Feature.objects.update_or_create(
    code="loyalty_program",
    defaults={"name": "Loyalty Program", "category": "marketing"},
)
```

### B. Add a new plan

```python
from apps.permissions.models import SubscriptionPlan, PlanFeature, Feature

plan, _ = SubscriptionPlan.objects.update_or_create(
    slug="agency",
    defaults={
        "name": "Agency",
        "price": 199,
        "max_users": 50,
        "max_stores": 20,
        "max_products": 50_000,
        "sort_order": 25,  # between Growth and Professional
    },
)

# Bind features
for code in ("customer_management", "marketing_campaigns", "advanced_reports"):
    feature = Feature.objects.get(code=code)
    PlanFeature.objects.update_or_create(plan=plan, feature=feature)
```

### C. Subscribe a store to a plan

```python
from apps.permissions.models import Subscription
from django.utils import timezone

Subscription.objects.update_or_create(
    store=store,
    defaults={
        "plan": plan,
        "status": "active",
        "starts_at": timezone.now(),
        "current_period_end": timezone.now() + timezone.timedelta(days=30),
    },
)
```

`status` choices: `trialing`, `active`, `past_due`, `canceled`, `expired`.

Only `active` and `trialing` (within trial window) gate features. Anything
else means "no features".

---

## 10. Wiring permission checks into your code

This is the day-to-day work for developers.

### Function view

```python
from apps.permissions.decorators import permission_required

@permission_required("orders.create")
def create_order(request):
    ...
```

For object-level checks (e.g. only the order's assignee can edit):

```python
@permission_required("orders.update", obj_kwarg="order_id")
def edit_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id)
    ...
```

You need to register how to load the object from the URL kwarg:

```python
# apps/yourapp/permissions.py  (or wherever)
from apps.permissions.decorators import register_object_loader
register_object_loader("order_id", "apps.orders.models.Order")
```

### CBV

```python
from apps.permissions.mixins import PermissionRequiredMixin

class OrderCreateView(PermissionRequiredMixin, View):
    permission_required = "orders.create"
    ...
```

For feature gating:

```python
from apps.permissions.mixins import FeatureRequiredMixin

class CampaignListView(FeatureRequiredMixin, View):
    required_feature = "marketing_campaigns"
    ...
```

For store-membership check:

```python
from apps.permissions.mixins import StoreAccessMixin

class AnyStoreView(StoreAccessMixin, View):
    ...
```

### DRF

```python
from apps.permissions.permissions import (
    HasPermission, HasFeature, IsStoreMember, HasStoreRole,
)

class OrderViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStoreMember, HasPermission]
    permission_code = "orders.view"            # checked at view level
    object_permission_code = "orders.update"  # checked at object level
```

Per-action override:

```python
def get_permissions(self):
    if self.action == "create":
        return [IsStoreMember(), HasPermission.with_code("orders.create")]
    if self.action in ("update", "partial_update"):
        return [IsStoreMember(), HasObjectPermission("orders.update")]
    return super().get_permissions()
```

### Programmatic check (anywhere)

```python
from apps.permissions.resolver import PermissionResolver

ok = PermissionResolver().check(user, store, "orders.create")
ok = PermissionResolver().check(user, store, "orders.update", obj=order)
ok = PermissionResolver().check_feature(user, store, "marketing_campaigns")
```

Or via the service helpers:

```python
from apps.permissions.services import (
    user_has_permission,
    user_has_feature,
    store_has_feature,
)

if user_has_permission(user, store, "orders.create"):
    ...
```

---

## 11. Templates, DRF, and JWT — at a glance

### Templates

```django
{% load rbac %}

{% can "orders.create" %}
  <a href="{% url 'orders:create' %}">New Order</a>
{% endcan %}

{% can_any "campaigns.view" "promo_codes.view" as can_market %}
{% if can_market %}
  <a href="{% url 'marketing:home' %}">Marketing</a>
{% endif %}

{% has_feature "marketing_campaigns" as has_pro %}
{% if has_pro %}
  <span class="badge bg-success">Pro</span>
{% endif %}

{% user_role current_store as role_name %}
<p>Logged in as: {{ role_name }}</p>
```

### DRF 403 response shape

The custom exception handler enriches 403 responses with machine-readable fields:

```json
{
  "error": "forbidden",
  "detail": "Permission denied.",
  "required_permission": "orders.delete",
  "required_feature": null
}
```

So your frontend can show a useful message ("You need the Order Manager role
to delete orders").

### JWT fast-path

If you wire `RBACTokenObtainPairSerializer` in `apps/accounts/urls_api.py`,
the JWT carries RBAC claims:

```json
{
  "email": "alice@example.com",
  "stores": ["uuid-1", "uuid-2"],
  "current_store_id": "uuid-1",
  "permissions": ["orders.view", "orders.create", ...],
  "features": ["customer_management"],
  "token_version": 1
}
```

Views can short-circuit with `jwt_fast_path_check`:

```python
from apps.accounts.jwt_rbac import jwt_fast_path_check

def has_permission(self, request, view):
    code = view.permission_code
    ok, trusted = jwt_fast_path_check(request, code)
    if trusted:
        return ok
    return PermissionResolver().check(request.user, request.store, code)
```

The fast-path only fires when:
- The token's `current_store_id` matches `request.store.id`
- The code is in the embedded `permissions` set

Otherwise it falls through to the full resolver.

---

## 12. Caching and invalidation

Permission checks are cached in Redis under keys shaped like:

```
rbac:user:<uid>:store:<sid>:perms:v<version>
rbac:user:<uid>:store:<sid>:features:v<version>:p<plan_version>
rbac:user:<uid>:version
rbac:store:<sid>:plan:version
```

The `version` stamp is bumped (not the key deleted) when something
changes. The resolver reads the latest stamp and uses it as part of the
cache key, so a bump effectively invalidates everything for that user /
store.

### What triggers an automatic bump

The `post_save`/`post_delete` signals in `apps/permissions/signals.py`
bump the relevant version stamp when:

- A `RolePermission` changes
- A `StoreMembership` is added/removed/updated
- A `UserPermissionOverride` is added/removed
- A `Subscription` / `SubscriptionPlan` / `PlanFeature` changes

In other words: **you don't have to do anything**. Save the row, the
cache invalidates.

### Manual invalidation (for management commands / Celery tasks)

```python
from apps.permissions.cache import (
    bump_user_version,
    bump_store_plan_version,
)

bump_user_version(user.id)
bump_store_plan_version(store.id)
```

### Bypass the cache in tests

```python
from django.core.cache import cache
cache.clear()
```

---

## 13. Audit log

Every change to a `Role`, `RolePermission`, `StoreMembership`,
`UserPermissionOverride`, `Subscription`, or `SubscriptionPlan` is
captured in `AuditLog` automatically.

Each row contains:

| Field | What it is |
|---|---|
| `actor` | The user who made the change (from request context) |
| `store` | The store the change relates to (if any) |
| `action` | e.g. `membership.create`, `role.update`, `permission_override.delete` |
| `target_type` | e.g. `StoreMembership`, `Role` |
| `target_id` | UUID of the changed row |
| `before` | JSON snapshot of the row before the change |
| `after` | JSON snapshot of the row after the change |
| `ip_address` | Request IP |
| `user_agent` | Request UA (truncated to 512 chars) |
| `request_id` | Correlation ID (from `X-Request-ID` header or generated) |
| `created_at` | Timestamp |

### View in admin

`/admin/permissions/auditlog/` — read-only, supports CSV export.

### Append-only

The `AuditLog.save()` and `AuditLog.delete()` methods both raise
`PermissionError`. The only way to add a row is via the signal handlers.

---

## 14. Troubleshooting

### "User can't do X but they should be able to"

1. **Are they a member of the store?**
   ```python
   StoreMembership.objects.filter(user=user, store=store, is_active=True).exists()
   ```

2. **Does their role grant the permission?**
   ```python
   RolePermission.objects.filter(
       role__slug="<their-role>",
       permission__code="<their-permission>",
       modifier="grant",
   ).exists()
   ```

3. **Is there a DENY override blocking them?**
   ```python
   UserPermissionOverride.objects.filter(
       user=user, store=store,
       permission__code="<the-permission>",
       is_granted=False,
   ).exists()
   ```

4. **Stale cache?** The version stamp should auto-bump on save, but if
   you suspect staleness, force it:
   ```python
   from apps.permissions.cache import bump_user_version
   bump_user_version(user.id)
   ```

5. **For features:** Does the store have a plan with the feature?
   ```python
   store.subscription.plan.plan_features.filter(feature__code="<the-feature>").exists()
   ```

### "Sidebar doesn't update after I change a role"

The sidebar is server-rendered. After a role change the user needs to
reload. The cache is invalidated server-side; the rendered HTML on the
client is just a snapshot.

### "I added a new resource to registry.py but it doesn't appear"

Run `python manage.py sync_permissions`. The registry is read at startup
but the DB rows are written by this command.

### "Permission denied for an admin user"

`is_superuser` bypasses ALL RBAC checks. If a superuser is being denied,
something else is wrong (e.g. CSRF, login session, view-level decorator
other than RBAC).

### "JWT says one set of permissions, resolver says another"

The JWT carries the snapshot at issue time. Use `token_version` to
detect staleness:

```python
from apps.permissions.cache import get_user_version

if token["token_version"] != get_user_version(user.id):
    # Token is stale; fall through to the resolver
```

The `RBACTokenObtainPairSerializer` bumps the token's `token_version`
on every login / refresh, so a re-login fixes drift.

---

## Quick reference card

```python
# Permission check (most common)
from apps.permissions.services import user_has_permission
user_has_permission(user, store, "orders.create")

# Feature check
from apps.permissions.services import user_has_feature
user_has_feature(user, store, "marketing_campaigns")

# Granular resolver
from apps.permissions.resolver import PermissionResolver
PermissionResolver().check(user, store, "orders.update", obj=order)

# Add a member
from apps.permissions.services import add_member
add_member(user, store, role, invited_by=admin_user)

# Bulk-revoke a permission
from apps.permissions.models import RolePermission
RolePermission.objects.filter(
    role__slug="viewer",
    permission__code="orders.delete",
).update(modifier="deny")

# Audit one change
from apps.permissions.models import AuditLog
AuditLog.objects.filter(
    target_type="StoreMembership",
    target_id=str(membership.id),
).order_by("-created_at")[:5]
```

```bash
# CLI
python manage.py sync_permissions              # apply registry
python manage.py sync_permissions --check      # CI gate
python manage.py seed roles                    # seed system roles
python manage.py seed plans                    # seed plans + features
python manage.py seed role-permissions         # seed the role-perm matrix
```

```django
{# Templates #}
{% load rbac %}
{% can "orders.create" %}...{% endcan %}
{% can_any "x" "y" as ok %}{% if ok %}...{% endif %}
{% has_feature "marketing_campaigns" as pro %}{% if pro %}...{% endif %}
```

---

**Still stuck?** Check the test suite at `apps/permissions/tests/` —
every feature has working examples.