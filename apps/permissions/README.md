# `apps.permissions` — RBAC & Subscription Gating

Authorization for the Social Commerce CRM. This app is the single source of
truth for who can do what in which store, on which plan.

It plugs into Django function views, DRF, template tags, and the admin — all
sharing the same `PermissionResolver`.

> **New to the system?** Read the end-to-end user guide at
> [`docs/RBAC_USER_GUIDE.md`](../../docs/RBAC_USER_GUIDE.md) for a
> step-by-step walkthrough including how to add members, create roles,
> bind permissions, write templates, and troubleshoot common issues.
> What follows here is a quick reference.

---

## 1. The 5 layers

Each request evaluates layers top-to-bottom. A deny at any layer
short-circuits the rest.

| # | Layer | Source of truth | Files |
|---|---|---|---|
| 1 | Subscription plan | `Subscription`, `PlanFeature` | `services.py`, `resolver.py` |
| 2 | Store membership | `StoreMembership` | `models.py`, `resolver.py` |
| 3 | Role permissions | `Role` + `RolePermission` | `models.py`, `registry.py`, `resolver.py` |
| 4 | User overrides | `UserPermissionOverride` | `models.py`, `resolver.py` |
| 5 | Object-level | registered checker | `object_permissions.py` |

DENY at any layer beats GRANT — privilege-escalation guard.

---

## 2. Adding a new permission

Edit `apps/permissions/registry.py` and add a resource under `RESOURCES`:

```python
RESOURCES = {
    "invoices": {
        "name": "Invoices",
        "category": "billing",
        "actions": ["view", "create", "export"],
    },
    ...
}
```

Then sync the DB:

```bash
python manage.py sync_permissions
```

This is idempotent and safe to run on every deploy. CI runs
`sync_permissions --check` and fails if the registry and DB drift.

---

## 3. Using it from views

### Function view

```python
from apps.permissions.decorators import permission_required

@permission_required("orders.create")
def create_order(request):
    ...
```

### CBV

```python
from apps.permissions.mixins import PermissionRequiredMixin

class OrderCreateView(PermissionRequiredMixin, View):
    permission_required = "orders.create"
    ...
```

### DRF

```python
from apps.permissions.permissions import HasPermission, IsStoreMember

class OrderViewSet(viewsets.ModelViewSet):
    permission_classes = [IsStoreMember, HasPermission]
    permission_code = "orders.view"
    object_permission_code = "orders.update"
```

### Plan feature

```python
from apps.permissions.decorators import feature_required

@feature_required("marketing_campaigns")
def campaigns(request):
    ...
```

---

## 4. Templates

```django
{% load rbac %}

{% can "orders.create" %}
  <a href="{% url 'orders:create' %}">New Order</a>
{% endcan %}

{% can_any "campaigns.view" "promo_codes.view" as can_market %}
{% if can_market %}
  <a href="{% url 'marketing:home' %}">Marketing</a>
{% endif %}

{% has_feature "marketing_campaigns" as has_marketing %}
{% if has_marketing %}
  <span class="badge bg-success">Pro Plan</span>
{% endif %}
```

---

## 5. Caching

Permission checks are cached in Redis with a version-stamp pattern.

- `rbac:user:{uid}:version` — bump this on any role/membership/override change
- `rbac:store:{sid}:plan:version` — bump on plan/subscription change

The resolver reads these stamps into the cache key, so a bump effectively
invalidates all of a user's cached permissions without enumerating keys.

To force a refresh from a management command or Celery task:

```python
from apps.permissions.cache import bump_user_version, bump_store_plan_version

bump_user_version(user.id)
bump_store_plan_version(store.id)
```

---

## 6. Audit logging

Every change to a `Role`, `RolePermission`, `StoreMembership`,
`UserPermissionOverride`, `Subscription`, or `SubscriptionPlan` is written to
`AuditLog` automatically (see `signals.py`).

The `AuditLog` model is **append-only** — `save()` and `delete()` raise
`PermissionError` for non-system updates.

View audit entries in Django admin under "Permissions → Audit logs". The
admin is read-only and supports CSV export.

---

## 7. Adding an object-level check

```python
# apps/permissions/object_permissions.py
from apps.permissions.object_permissions import register_checker

@register_checker("orders")
def order_object_checker(user, store, code, order):
    # Sales Agents see only assigned orders; Managers+ see everything.
    if user.is_superuser:
        return True
    m = StoreMembership.objects.filter(
        user=user, store=order.store, is_active=True,
    ).select_related("role").order_by("-role__level").first()
    if not m:
        return False
    if m.role.level >= 60:  # Manager+
        return True
    return order.assignees.filter(pk=user.pk).exists()
```

The resolver calls this automatically when the permission check has
`obj=` set.

---

## 8. JWT integration

`apps/accounts/serializers_rbac.py::RBACTokenObtainPairSerializer` embeds the
user's RBAC claims in the access token. Views can short-circuit with:

```python
from apps.accounts.jwt_rbac import jwt_fast_path_check

def has_permission(self, request, view):
    ok, trusted = jwt_fast_path_check(request, "orders.view")
    if trusted:
        return ok
    return PermissionResolver().check(request.user, request.store, "orders.view")
```

The fast-path only fires when the token's `current_store_id` matches
`request.store.id` and the embedded `permissions` set is fresh. Otherwise
the full resolver runs.

---

## 9. CLI helpers

```bash
# Sync registry → DB
python manage.py sync_permissions
python manage.py sync_permissions --check   # CI gate

# Seed roles / plans / permissions
python manage.py seed roles
python manage.py seed plans
python manage.py seed role-permissions
```

---

## 10. Tests

```bash
pytest apps/permissions/tests/ -v
```

Current coverage on the permissions app source: **86%**.

Test layout:

- `test_registry.py` — registry → DB sync
- `test_resolver.py` — 5-layer evaluation + cache
- `test_cache.py` — version-stamp helpers
- `test_drf_permissions.py` — DRF permission classes
- `test_template_tags.py` — `{% can %}`, `{% can_any %}`, etc.
- `test_template_integration.py` — sidebar/topnav rendering
- `test_object_permissions.py` — object-level checkers
- `test_seeders.py` — role/plan/permission seeders
- `test_subscription.py` — plan feature gating
- `test_audit.py` + `test_audit_admin.py` — audit signals + admin
- `test_legacy_migration.py` — M2M → StoreMembership migration
- `test_jwt_rbac.py` — RBAC claims in JWT
- `test_services.py` — service-layer helpers
- `test_decorators_mixins_middleware.py` — view integration glue

---

## 11. Migration: legacy M2Ms → `StoreMembership`

The old `Store.owners/managers/staff` M2M fields still exist during the
cutover. Migration `0002_migrate_legacy_memberships` copies them into
`StoreMembership` rows.

It is **idempotent** — running it twice produces no duplicates — and
**safe to re-run after `seed roles`** if seeders weren't in place the first
time.

`Store.is_owner(user)` etc. delegate to `StoreMembership` first, then fall
back to the M2M. After all consumers migrate, the M2Ms can be dropped.