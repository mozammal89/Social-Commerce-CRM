"""
Context processors for the role/permission management UI.

These inject breadcrumbs and a sidebar section override into every
template render so the layout components pick them up automatically.
"""

from __future__ import annotations

from django.urls import NoReverseMatch, reverse


def role_permission_breadcrumbs(request):
    """
    Build the breadcrumb list for any role/permission page.

    Inspects ``request.resolver_match`` to find the URL name, then
    walks the namespace hierarchy building a chain:
        Dashboard → Roles & Permissions → <page name>

    Returns an empty list when the current URL is not under
    the ``role_permission`` namespace.
    """
    match = getattr(request, "resolver_match", None)
    if not match or match.app_name != "role_permission":
        return {"rp_breadcrumbs": []}

    PAGE_TITLES = {
        "role_list": "Roles",
        "role_create": "New role",
        "role_detail": "Role details",
        "role_edit": "Edit role",
        "role_delete": "Delete role",
        "role_clone": "Clone role",
        "role_toggle_permission": "Toggle permission",
        "member_list": "Members",
        "member_add": "Add member",
        "member_change_role": "Change role",
        "member_deactivate": "Deactivate member",
        "permission_catalog": "Permission catalog",
        "audit_log": "Audit log",
        "audit_export": "Export audit log",
    }

    SECTION = {
        "roles": ("Roles & Permissions", reverse("role_permission:role_list")),
        "members": ("Roles & Permissions", reverse("role_permission:member_list")),
        "permission": ("Roles & Permissions", reverse("role_permission:permission_catalog")),
        "audit": ("Roles & Permissions", reverse("role_permission:audit_log")),
    }

    url_name = match.url_name or ""
    section_key = (
        "roles" if url_name.startswith("role_")
        else "members" if url_name.startswith("member_")
        else "permission" if url_name.startswith("permission_")
        else "audit" if url_name.startswith("audit_")
        else "roles"
    )

    section_title, section_url = SECTION[section_key]
    crumbs = [{"title": "Dashboard", "url": reverse("dashboard:home")}]
    crumbs.append({"title": section_title, "url": section_url})

    # On list pages, the section link is the leaf
    if url_name in ("role_list", "member_list", "permission_catalog", "audit_log"):
        crumbs[-1]["url"] = None

    # On detail/edit pages, add the role list crumb
    if section_key == "roles" and url_name not in ("role_list", "role_create"):
        crumbs.append({
            "title": "All roles",
            "url": reverse("role_permission:role_list"),
        })

    # Final leaf
    page_title = PAGE_TITLES.get(url_name, "Roles & Permissions")
    crumbs.append({"title": page_title, "url": None})

    return {"rp_breadcrumbs": crumbs}


def role_permission_sidebar_extra(request):
    """
    Inject an ``rp_sidebar_extra`` template fragment that the sidebar
    can include to render a "Roles & Permissions" section. Templates
    that want it should render the ``role_permission/components/sidebar_section.html``
    include at the appropriate place.

    For now this is just a flag the template can check.
    """
    match = getattr(request, "resolver_match", None)
    in_section = bool(match and match.app_name == "role_permission")
    return {"rp_in_section": in_section}


def role_permission_global_assets(request):
    """
    Inject path variables for the global navbar fix stylesheet.

    Templates that want to apply the navbar fix on every page should
    include this in the ``extra_css`` block::

        <link rel="stylesheet" href="{{ RP_NAVBAR_FIX_CSS }}">

    Returning the URL via a context variable means we don't have to
    modify the existing ``layouts/base.html`` to load it.
    """
    return {
        "RP_NAVBAR_FIX_CSS": "permissions/css/navbar_fix.css",
    }
