"""
Seeds the four default plans and binds their feature lists.

Idempotent: running it twice has no effect.
"""

from __future__ import annotations

from apps.core.seeders.base import BaseSeeder
from apps.subscriptions.models import Feature, PlanFeature, SubscriptionPlan


PLAN_MATRIX: list[dict] = [
    {
        "slug": "starter",
        "name": "Starter",
        "price": 19,
        "sort_order": 10,
        "max_users": 3,
        "max_stores": 1,
        "max_products": 500,
        "max_orders_per_month": 1000,
        "max_warehouses": 1,
        "trial_days": 14,
        "features": [
            "customer_management",
            "basic_reports",
        ],
    },
    {
        "slug": "growth",
        "name": "Growth",
        "price": 49,
        "sort_order": 20,
        "max_users": 10,
        "max_stores": 3,
        "max_products": 5000,
        "max_orders_per_month": 10000,
        "max_warehouses": 3,
        "trial_days": 14,
        "features": [
            "customer_management",
            "inventory_management",
            "marketing_campaigns",
            "advanced_reports",
            "team_management",
        ],
    },
    {
        "slug": "professional",
        "name": "Professional",
        "price": 99,
        "sort_order": 30,
        "max_users": 25,
        "max_stores": 10,
        "max_products": 25000,
        "max_orders_per_month": 50000,
        "max_warehouses": 10,
        "trial_days": 14,
        "features": [
            "customer_management",
            "inventory_management",
            "marketing_campaigns",
            "advanced_reports",
            "team_management",
            "multi_warehouse",
            "api_access",
            "facebook_integration",
            "whatsapp_integration",
        ],
    },
    {
        "slug": "enterprise",
        "name": "Enterprise",
        "price": 299,
        "sort_order": 40,
        "max_users": 999,
        "max_stores": 999,
        "max_products": 999_999,
        "max_orders_per_month": 999_999,
        "max_warehouses": 999,
        "trial_days": 30,
        "features": [
            "customer_management",
            "inventory_management",
            "marketing_campaigns",
            "advanced_reports",
            "team_management",
            "multi_warehouse",
            "api_access",
            "facebook_integration",
            "whatsapp_integration",
            "sso",
            "audit_export",
        ],
    },
]


class PlansSeeder(BaseSeeder):
    name = "plans"

    def run(self) -> None:
        for spec in PLAN_MATRIX:
            features = spec.pop("features")
            plan, _ = SubscriptionPlan.objects.update_or_create(
                slug=spec["slug"],
                defaults=spec,
            )
            for code in features:
                feature, _ = Feature.objects.get_or_create(
                    code=code,
                    defaults={
                        "name": code.replace("_", " ").title(),
                        "category": "general",
                    },
                )
                PlanFeature.objects.update_or_create(
                    plan=plan,
                    feature=feature,
                    defaults={"limit_value": None},
                )
