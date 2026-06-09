"""
Admin configuration for stores app.
"""

from django.contrib import admin
from apps.stores.models import Store


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    """Admin interface for Store model."""

    list_display = [
        "name",
        "slug",
        "status",
        "created_at",
        "owner_count",
        "manager_count",
        "staff_count",
    ]
    list_filter = [
        "status",
        "created_at",
        "is_deleted",
    ]
    search_fields = [
        "name",
        "slug",
        "description",
    ]
    ordering = ["-created_at"]
    readonly_fields = [
        "id",
        "slug",
        "created_at",
        "updated_at",
    ]
    filter_horizontal = [
        "owners",
        "managers",
        "staff",
    ]

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "slug",
                    "description",
                    "logo",
                ),
            },
        ),
        (
            "Status",
            {
                "fields": (
                    "status",
                    "is_deleted",
                ),
            },
        ),
        (
            "People",
            {
                "fields": (
                    "owners",
                    "managers",
                    "staff",
                ),
            },
        ),
        (
            "Settings",
            {
                "fields": ("settings",),
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "id",
                    "created_at",
                    "updated_at",
                    "deleted_at",
                    "deleted_by",
                ),
            },
        ),
    )

    def owner_count(self, obj):
        """Return count of store owners."""
        return obj.owners.count()

    owner_count.short_description = "Owners"

    def manager_count(self, obj):
        """Return count of store managers."""
        return obj.managers.count()

    manager_count.short_description = "Managers"

    def staff_count(self, obj):
        """Return count of store staff."""
        return obj.staff.count()

    staff_count.short_description = "Staff"

    def get_queryset(self, request):
        """Return queryset including soft-deleted stores for admin."""
        return super().get_queryset(request)
