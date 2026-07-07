"""
Django admin registrations for the subscription system.
"""

from __future__ import annotations

from django.contrib import admin

from .models import (
    Feature,
    PlanFeature,
    Subscription,
    SubscriptionEvent,
    SubscriptionPlan,
)


# ---------------------------------------------------------------------------
# Feature
# ---------------------------------------------------------------------------
@admin.register(Feature)
class FeatureAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "category")
    list_filter = ("category",)
    search_fields = ("code", "name", "description")
    readonly_fields = ("created_at", "updated_at")


# ---------------------------------------------------------------------------
# PlanFeature (inline)
# ---------------------------------------------------------------------------
class PlanFeatureInline(admin.TabularInline):
    model = PlanFeature
    extra = 0
    autocomplete_fields = ("feature",)


# ---------------------------------------------------------------------------
# SubscriptionPlan
# ---------------------------------------------------------------------------
@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "slug",
        "price",
        "billing_period",
        "is_active",
        "is_public",
        "max_users",
        "max_stores",
        "sort_order",
    )
    list_filter = ("is_active", "is_public", "billing_period")
    search_fields = ("name", "slug", "description")
    inlines = (PlanFeatureInline,)
    readonly_fields = ("created_at", "updated_at")
    ordering = ("sort_order", "price")


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------
@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display = ("get_display_name", "plan", "status", "current_period_end", "trial_ends_at")
    list_filter = ("status", "plan")
    search_fields = ("tenant__name", "store__name", "stripe_customer_id", "stripe_subscription_id")
    autocomplete_fields = ("tenant", "store", "plan")
    readonly_fields = ("created_at", "updated_at")

    def get_display_name(self, obj):
        """Display either tenant or store name for migration period."""
        if obj.tenant:
            return f"Tenant: {obj.tenant.name}"
        elif obj.store:
            return f"Store: {obj.store.name}"
        else:
            return "No tenant or store (migration incomplete)"

    get_display_name.short_description = "Tenant/Store"


# ---------------------------------------------------------------------------
# SubscriptionEvent
# ---------------------------------------------------------------------------
@admin.register(SubscriptionEvent)
class SubscriptionEventAdmin(admin.ModelAdmin):
    list_display = ("subscription", "event_type", "occurred_at", "actor")
    list_filter = ("event_type",)
    search_fields = ("subscription__tenant__name", "event_type")
    readonly_fields = ("created_at", "updated_at")
    date_hierarchy = "occurred_at"
