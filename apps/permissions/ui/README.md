# Role & Permission Management UI

Dashboard pages for managing roles, permissions, store memberships, and
audit logs. This is a **sub-app of `apps.permissions`** — it shares the
same models, registry, and resolver, but lives under its own
`apps/permissions/ui/` folder for clean separation of UI concerns.

Supports both **superuser** (cross-store) and **store admin**
(single-store scope) workflows.

## Folder layout

```
apps/permissions/                      # Core RBAC app
├── models.py                          # Role, Permission, StoreMembership, …
├── services.py                        # Resolver, helpers
├── registry.py                        # Permission/resource registry
└── ui/                                # ← THIS sub-app (UI layer only)
    ├── apps.py
    ├── constants.py                   # Permission codes used by the UI
    ├── mixins.py                      # Auth/permission mixins
    ├── services.py                    # Mutations (with audit logging)
    ├── forms.py
    ├── views.py
    ├── urls.py                        # namespace: role_permission
    ├── context_processors.py
    ├── templatetags/
    │   ├── rp_ui.py                   # {% rp_breadcrumbs %} etc.
    ├── static/permissions/
    │   ├── css/role_permission.css    # Small overrides on top of global
    │   └── js/rp/                     # app.js, matrix.js, role-form.js,
    │                                  # member-list.js
    └── README.md

templates/
└── role_permission/                   # All UI templates
    ├── components/
    │   ├── sidebar_section.html       # Sidebar nav block
    │   ├── role_card.html             # Reusable role card
    │   └── permission_row.html        # Reusable permission row
    ├── roles/
    │   ├── role_list.html
    │   ├── role_detail.html
    │   └── role_form.html
    ├── members/
    │   ├── member_list.html
    │   └── member_add.html
    ├── permissions/
    │   └── permission_catalog.html
    └── audit/
        └── audit_log.html
```

## Installation

1. Add `"apps.permissions.ui"` to `INSTALLED_APPS` in your settings.

2. Include the URLs in your main `dashboard/urls.py` (or wherever your
   dashboard routes live):

   ```python
   from django.urls import include, path

   urlpatterns = [
       path("dashboard/", include("apps.dashboard.urls")),
       path("dashboard/", include(("apps.permissions.ui.urls", "role_permission"))),
   ]
   ```

3. Register the context processors in `settings.TEMPLATES[0].OPTIONS.context_processors`:

   ```python
   "apps.permissions.ui.context_processors.role_permission_breadcrumbs",
   "apps.permissions.ui.context_processors.role_permission_sidebar_extra",
   ```

4. Make sure these permission codes exist in your registry:
   - `roles.view`, `roles.manage`
   - `members.view`, `members.manage`
   - `permissions.view`
   - `audit.view`

5. `python manage.py collectstatic` to gather the new static files.

6. **To expose the "Roles & Permissions" sidebar block** in the global
   sidebar, add the following line to
   `templates/components/sidebar.html` *inside* the `<nav class="sidebar-nav">`
   (anywhere before the help section):

   ```django
   {% include "role_permission/components/sidebar_section.html" %}
   ```

   This is the only change required to the existing layout — the rest
   of the UI works without any modifications to other files.

## URL namespace

All URLs are namespaced as `role_permission:`. Examples:

- `{% url 'role_permission:role_list' %}`
- `{% url 'role_permission:role_detail' role_id=role.id %}`
- `{% url 'role_permission:member_add' %}`
- `{% url 'role_permission:audit_log' %}`

## Authorization model

| Action                       | Superuser | Store Admin (with `roles.manage`) |
|------------------------------|-----------|-----------------------------------|
| View roles                   | All       | System + own store's roles        |
| Create role                  | System + Custom | Custom only                  |
| Edit role                    | All       | Custom only                       |
| Delete role                  | All       | Custom only (soft-deactivate)     |
| Clone role                   | All       | All                               |
| Toggle permission on role    | All       | Custom only                       |
| Manage members               | All stores| Own store                         |
| View audit log               | All       | Own store                         |
| Export audit log (CSV)       | Yes       | No                                |
| Manage system roles          | Yes       | No                                |

The mixin `apps.permissions.ui.mixins.StoreScopedPermissionMixin` is the
gatekeeper: it short-circuits superusers and uses
`apps.permissions.services.user_has_permission` for everyone else.

## Service-layer mutations

**Never** call the ORM directly from views for mutations. Use the
service functions in `apps/permissions/ui/services.py`:

- `create_role(...)`, `update_role(...)`, `delete_role(...)`, `clone_role(...)`
- `set_role_permissions(...)`, `toggle_role_permission(...)`
- `add_member(...)`, `change_member_role(...)`, `deactivate_member(...)`
- `set_user_override(...)`, `clear_user_override(...)`

Every mutation:
1. Checks the actor has authority.
2. Wraps writes in `transaction.atomic()`.
3. Emits an `AuditLog` entry with before/after state.
4. Captures IP / user-agent / request-id from the request object.

## Design choices

- **No new app**: this lives as a sub-app of `apps.permissions` to keep
  all RBAC code in one place. The `ui` subfolder is purely for code
  organization.
- **No separate base template**: every page extends
  `layouts/dashboard.html`, the project's existing layout. Sidebar,
  top nav, breadcrumbs, and footer are inherited.
- **Project design system**: all colors, spacing, and typography come
  from the project's CSS variables. We use Bootstrap utility classes
  and Bootstrap Icons (matching the rest of the dashboard).
- **Reuse existing components**: `empty_state.html`, `pagination.html`,
  `messages.html`, `form.html`, `table.html` — all already in
  `templates/components/`.
- **RBAC template tags**: use the existing `{% can %}` and `{% can_any %}`
  tags from `apps/permissions/templatetags/rbac.py`.
- **No global JS**: vanilla ES modules, one per concern.
- **No `!important`**: relies on the project's CSS variables and class
  composition.

## Security

- CSRF is enforced on all POST/PUT/DELETE views.
- The CSRF token is read from the form's hidden field for AJAX.
- All permission checks happen server-side. UI hiding is UX, not security.
- System roles cannot be deleted; they are deactivated.
- Roles with active members are deactivated, not hard-deleted.
- The audit log is append-only (enforced by `AuditLog.save`).