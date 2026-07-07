"""
Django admin registrations for the RBAC system.

Notes:
- System roles / system permissions are read-only in the admin to prevent
  accidental breakage of the registered system.
- AuditLog is read-only with a CSV export action.
"""

from __future__ import annotations

import csv

from django.contrib import admin, messages
from django.http import HttpResponse
from django.utils.translation import gettext_lazy as _

from .constants import MODIFIER_GRANT
from .models import (
    AuditLog,
    Permission,
    Resource,
    Role,
    RolePermission,
    StoreMembership,
    UserPermissionOverride,
)
from apps.subscriptions.models import (
    Feature,
    PlanFeature,
    Subscription,
    SubscriptionEvent,
    SubscriptionPlan,
)


# ---------------------------------------------------------------------------
# Resource / Permission
# ---------------------------------------------------------------------------
@admin.register(Resource)
class ResourceAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category", "is_active", "updated_at")
    list_filter = ("category", "is_active")
    search_fields = ("code", "name", "description")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("category", "code")


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ("code", "resource", "action", "name", "is_system")
    list_filter = ("resource", "action", "is_system")
    search_fields = ("code", "name", "description")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("code",)

    def get_readonly_fields(self, request, obj=None):
        # System permissions: even name/description are editable, but the
        # code/action/resource triple is locked.
        if obj and obj.is_system:
            return ("code", "resource", "action", "is_system", "created_at", "updated_at")
        return ("created_at", "updated_at")


# ---------------------------------------------------------------------------
# Role / RolePermission
# ---------------------------------------------------------------------------
class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 0
    autocomplete_fields = ("permission",)
    raw_id_fields = ()
    fields = ("permission", "modifier")


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "level", "is_system", "is_active", "store")
    list_filter = ("is_system", "is_active", "store")
    search_fields = ("name", "slug", "description")
    readonly_fields = ("created_at", "updated_at")
    inlines = (RolePermissionInline,)

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.is_system:
            return (
                "name",
                "slug",
                "is_system",
                "level",
                "inherits_from",
                "created_at",
                "updated_at",
            )
        return ("created_at", "updated_at")

    def has_delete_permission(self, request, obj=None):
        if obj and obj.is_system:
            return False
        return super().has_delete_permission(request, obj)


# ---------------------------------------------------------------------------
# Membership / Override
# ---------------------------------------------------------------------------
@admin.register(StoreMembership)
class StoreMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "store", "role", "is_active", "joined_at", "invited_by")
    list_filter = ("is_active", "store", "role")
    search_fields = ("user__email", "store__name", "role__name")
    autocomplete_fields = ("user", "store", "role", "invited_by")
    raw_id_fields = ("user", "store", "role", "invited_by")
    readonly_fields = ("joined_at", "created_at", "updated_at")


@admin.register(UserPermissionOverride)
class UserPermissionOverrideAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "permission",
        "store",
        "is_granted",
        "expires_at",
        "granted_by",
        "created_at",
    )
    list_filter = ("is_granted", "store")
    search_fields = ("user__email", "permission__code", "reason")
    autocomplete_fields = ("user", "store", "permission", "granted_by")
    readonly_fields = ("created_at", "updated_at")


# ---------------------------------------------------------------------------
# AuditLog — read-only with CSV export
# ---------------------------------------------------------------------------
@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "action",
        "target_type",
        "target_id",
        "actor",
        "store",
        "ip_address",
    )
    list_filter = ("action", "target_type", "store")
    search_fields = (
        "action",
        "target_type",
        "target_id",
        "actor__email",
        "ip_address",
        "request_id",
    )
    date_hierarchy = "created_at"
    readonly_fields = (
        "actor",
        "store",
        "action",
        "target_type",
        "target_id",
        "before",
        "after",
        "ip_address",
        "user_agent",
        "request_id",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    actions = ("export_csv",)

    @admin.action(description=_("Export selected to CSV"))
    def export_csv(self, request, queryset):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="audit_log.csv"'
        writer = csv.writer(response)
        writer.writerow(
            [
                "created_at",
                "action",
                "target_type",
                "target_id",
                "actor_email",
                "store_id",
                "ip",
                "request_id",
            ]
        )
        for row in queryset.select_related("actor", "store"):
            writer.writerow(
                [
                    row.created_at.isoformat(),
                    row.action,
                    row.target_type,
                    row.target_id,
                    row.actor.email if row.actor else "",
                    str(row.store_id) if row.store_id else "",
                    row.ip_address or "",
                    row.request_id or "",
                ]
            )
        return response
