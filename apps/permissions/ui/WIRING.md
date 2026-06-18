# Wiring the Role & Permission UI into the dashboard

The UI code is complete and lives in `apps/permissions/ui/` and
`templates/role_permission/`. To make it visible in the dashboard,
three small changes are needed.

---

## Step 1 — Register the sub-app

In **`config/settings/base.py`**, add `"apps.permissions.ui"` to the
`LOCAL_APPS` list:

```python
LOCAL_APPS = [
    "apps.accounts",
    "apps.stores",
    "apps.common",
    "apps.core",
    "apps.dashboard",
    "apps.permissions",
    "apps.permissions.ui",          # ← add this line
]
```

---

## Step 2 — Register context processors

In the same file, inside `TEMPLATES[0]["OPTIONS"]["context_processors"]`,
add the two entries below the existing `apps.permissions.context_processors.rbac`:

```python
"context_processors": [
    "django.template.context_processors.debug",
    "django.template.context_processors.request",
    "django.contrib.auth.context_processors.auth",
    "django.contrib.messages.context_processors.messages",
    "apps.common.context_processors.app_settings",
    "apps.common.context_processors.current_store",
    "apps.permissions.context_processors.rbac",
    "apps.permissions.ui.context_processors.role_permission_breadcrumbs",  # ← add
    "apps.permissions.ui.context_processors.role_permission_sidebar_extra", # ← add
],
```

---

## Step 3 — Include the URLs

In **`config/urls.py`**, add one line in the `urlpatterns` list:

```python
urlpatterns = [
    path("", home, name="home"),
    path("admin/", admin.site.urls),
    path("dashboard/", include("apps.dashboard.urls")),
    path("dashboard/roles/", include(("apps.permissions.ui.urls", "role_permission"))),  # ← add
    # … rest unchanged
]
```

---

## Step 4 — Add the sidebar block

In **`templates/components/sidebar.html`**, inside `<nav class="sidebar-nav">`
(anywhere before the Help section), add:

```django
{% include "role_permission/components/sidebar_section.html" %}
```

This single include renders the "Roles & Permissions" sidebar block —
gated by the permission checks — so the menu only appears for users
who have `roles.view`, `members.view`, `permissions.view`, or
`audit.view`.

---

## Step 5 — Collect static files

```bash
python manage.py collectstatic --noinput
```

---

## Step 6 — Register the permission codes

Make sure these codes exist in your registry (or run your seeder):

- `roles.view`, `roles.manage`
- `members.view`, `members.manage`
- `permissions.view`
- `audit.view`

You can register them via your existing seeders, e.g.:

```python
# apps/permissions/seeders/...
registry.register(code="roles.view", name="View roles", category="rbac")
registry.register(code="roles.manage", name="Manage roles", category="rbac")
registry.register(code="members.view", name="View members", category="rbac")
registry.register(code="members.manage", name="Manage members", category="rbac")
registry.register(code="permissions.view", name="View permissions", category="rbac")
registry.register(code="audit.view", name="View audit log", category="rbac")
```

Then run:

```bash
python manage.py shell -c "from apps.permissions.registry import sync_permissions; sync_permissions()"
```

(or whatever your existing sync command is).

---

## Verify

After these steps, the following URLs should work:

- `/dashboard/roles/` — role list
- `/dashboard/roles/<uuid>/` — role detail
- `/dashboard/roles/new/` — create role
- `/dashboard/members/` — member list
- `/dashboard/members/add/` — add member
- `/dashboard/permissions/` — permission catalog
- `/dashboard/audit/` — audit log
- `/dashboard/audit/export.csv` — CSV export (superuser only)

And in the sidebar, a new "Roles & Permissions" section should appear
(with sub-items: Roles, Members, Permissions, Audit log) — but only
for users who have the relevant permission code.