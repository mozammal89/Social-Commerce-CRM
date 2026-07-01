from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from apps.accounts.models import User, Tenant


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin interface for User model."""

    list_display = [
        "email",
        "first_name",
        "last_name",
        "role",
        "is_active",
        "is_staff",
        "is_superuser",
        "created_at",
        "email_verified",
        "phone_verified",
    ]
    list_filter = [
        "is_active",
        "is_staff",
        "is_superuser",
        "role",
        "email_verified",
        "phone_verified",
        "created_at",
        "is_deleted",
    ]
    search_fields = [
        "email",
        "first_name",
        "last_name",
        "phone_number",
    ]
    ordering = ["-created_at"]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "last_login",
        "login_count",
        "last_login_ip",
    ]

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "Personal Information",
            {
                "fields": (
                    "first_name",
                    "last_name",
                    "phone_number",
                    "avatar",
                ),
            },
        ),
        (
            "Role & Status",
            {
                "fields": (
                    "role",
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "email_verified",
                    "phone_verified",
                ),
            },
        ),
        (
            "Security",
            {
                "fields": (
                    "last_login",
                    "last_login_ip",
                    "login_count",
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "id",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
        (
            "Soft Delete",
            {
                "fields": (
                    "is_deleted",
                    "deleted_at",
                    "deleted_by",
                ),
            },
        ),
        (
            "Permissions",
            {
                "fields": (
                    "user_permissions",
                    "groups",
                ),
            },
        ),
        (
            "Subscriptions",
            {
                "fields": (
                    "pending_plan_slug",
                    "pending_trial_start",
                    "pending_subscription_date",
                ),
            },
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "email",
                    "first_name",
                    "last_name",
                    "phone_number",
                    "password1",
                    "password2",
                ),
            },
        ),
    )

    def get_queryset(self, request):
        """Return queryset including soft-deleted users for admin."""
        return super().get_queryset(request)


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    """Admin interface for Tenant model."""

    list_display = [
        "name",
        "slug",
        "owner",
        "is_active",
        "created_at",
    ]
    list_filter = [
        "is_active",
        "created_at",
    ]
    search_fields = [
        "name",
        "slug",
        "owner__email",
    ]
    ordering = ["-created_at"]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
    ]

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "name",
                    "slug",
                    "owner",
                    "is_active",
                ),
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "id",
                    "created_at",
                    "updated_at",
                ),
            },
        ),
    )
