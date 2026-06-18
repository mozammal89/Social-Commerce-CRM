"""
URL configuration for the role/permission management UI.

All URLs are namespaced under ``role_permission``. The dashboard's main
``urls.py`` should include this module with that namespace.
"""

from __future__ import annotations

from django.urls import path

from . import views

app_name = "role_permission"

urlpatterns = [
    # ---- Roles ----
    path("roles/", views.RoleListView.as_view(), name="role_list"),
    path("roles/new/", views.RoleCreateView.as_view(), name="role_create"),
    path("roles/<uuid:role_id>/", views.RoleDetailView.as_view(), name="role_detail"),
    path("roles/<uuid:role_id>/edit/", views.RoleUpdateView.as_view(), name="role_edit"),
    path("roles/<uuid:role_id>/delete/", views.RoleDeleteView.as_view(), name="role_delete"),
    path("roles/<uuid:role_id>/clone/", views.RoleCloneView.as_view(), name="role_clone"),
    path(
        "roles/<uuid:role_id>/toggle-permission/",
        views.RolePermissionToggleView.as_view(),
        name="role_toggle_permission",
    ),

    # ---- Members ----
    path("members/", views.MemberListView.as_view(), name="member_list"),
    path("members/add/", views.MemberAddView.as_view(), name="member_add"),
    path(
        "members/<uuid:membership_id>/change-role/",
        views.MemberChangeRoleView.as_view(),
        name="member_change_role",
    ),
    path(
        "members/<uuid:membership_id>/deactivate/",
        views.MemberDeactivateView.as_view(),
        name="member_deactivate",
    ),

    # ---- Permission catalog ----
    path("permissions/", views.PermissionCatalogView.as_view(), name="permission_catalog"),

    # ---- Audit log ----
    path("audit/", views.AuditLogListView.as_view(), name="audit_log"),
    path("audit/export.csv", views.AuditLogExportView.as_view(), name="audit_export"),
]
