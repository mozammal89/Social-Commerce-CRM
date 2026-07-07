from django.core.management.base import BaseCommand
from django.db import transaction
from apps.subscriptions.models import SubscriptionPlan, Feature
from datetime import timedelta
from django.utils import timezone


class Command(BaseCommand):
    help = "Create default subscription plans and features"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Creating subscription plans..."))

        # Define features
        features_data = [
            {"code": "customer_management", "name": "Customer Management", "category": "Core"},
            {"code": "basic_reports", "name": "Basic Reports", "category": "Analytics"},
            {"code": "inventory_management", "name": "Inventory Management", "category": "Core"},
            {"code": "marketing_campaigns", "name": "Marketing Campaigns", "category": "Marketing"},
            {"code": "advanced_reports", "name": "Advanced Reports", "category": "Analytics"},
            {"code": "team_management", "name": "Team Management", "category": "Core"},
            {"code": "multi_warehouse", "name": "Multi-Warehouse", "category": "Inventory"},
            {"code": "api_access", "name": "API Access", "category": "Integration"},
            {
                "code": "facebook_integration",
                "name": "Facebook Integration",
                "category": "Integration",
            },
            {
                "code": "whatsapp_integration",
                "name": "WhatsApp Integration",
                "category": "Integration",
            },
            {"code": "sso", "name": "Single Sign-On (SSO)", "category": "Security"},
            {"code": "audit_export", "name": "Audit Log Export", "category": "Security"},
        ]

        # Create features
        features = {}
        with transaction.atomic():
            for feature_data in features_data:
                feature, created = Feature.objects.get_or_create(
                    code=feature_data["code"],
                    defaults={
                        "name": feature_data["name"],
                        "category": feature_data["category"],
                        "description": f"{feature_data['name']} feature for Social Commerce CRM",
                    },
                )
                features[feature_data["code"]] = feature
                status = "Created" if created else "Already exists"
                self.stdout.write(f"  {status}: {feature.name} ({feature.code})")

        # Define subscription plans
        plans_data = [
            {
                "name": "Starter",
                "slug": "starter",
                "description": "Perfect for small businesses getting started with social commerce.",
                "price": 0,
                "currency": "BDT",
                "billing_period": "monthly",
                "max_stores": 1,
                "max_users": 2,
                "max_products": 100,
                "max_orders_per_month": 500,
                "max_warehouses": 1,
                "trial_days": 14,
                "sort_order": 1,
                "features": ["customer_management", "basic_reports", "inventory_management"],
            },
            {
                "name": "Growth",
                "slug": "growth",
                "description": "For growing businesses that need more power and features.",
                "price": 5000,
                "currency": "BDT",
                "billing_period": "monthly",
                "max_stores": 3,
                "max_users": 5,
                "max_products": 1000,
                "max_orders_per_month": 2000,
                "max_warehouses": 2,
                "trial_days": 14,
                "sort_order": 2,
                "features": [
                    "customer_management",
                    "basic_reports",
                    "inventory_management",
                    "marketing_campaigns",
                    "team_management",
                    "facebook_integration",
                    "whatsapp_integration",
                ],
            },
            {
                "name": "Professional",
                "slug": "professional",
                "description": "For established businesses needing advanced features and higher limits.",
                "price": 15000,
                "currency": "BDT",
                "billing_period": "monthly",
                "max_stores": 10,
                "max_users": 15,
                "max_products": 5000,
                "max_orders_per_month": 10000,
                "max_warehouses": 5,
                "trial_days": 14,
                "sort_order": 3,
                "features": [
                    "customer_management",
                    "basic_reports",
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
            {
                "name": "Enterprise",
                "slug": "enterprise",
                "description": "For large businesses with unlimited potential and premium support.",
                "price": 45000,
                "currency": "BDT",
                "billing_period": "monthly",
                "max_stores": 50,
                "max_users": 50,
                "max_products": 50000,
                "max_orders_per_month": 50000,
                "max_warehouses": 10,
                "trial_days": 30,
                "sort_order": 4,
                "features": [
                    "customer_management",
                    "basic_reports",
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

        # Create plans
        with transaction.atomic():
            for plan_data in plans_data:
                plan_features = plan_data.pop("features")
                plan, created = SubscriptionPlan.objects.get_or_create(
                    slug=plan_data["slug"], defaults=plan_data
                )

                # Update plan if it exists
                if not created:
                    for key, value in plan_data.items():
                        setattr(plan, key, value)
                    plan.save()

                # Associate features
                plan.features.clear()
                for feature_code in plan_features:
                    if feature_code in features:
                        plan.features.add(features[feature_code])

                status = "Created" if created else "Updated"
                self.stdout.write(
                    f"  {status}: {plan.name} ({plan.slug}) - {plan.currency}{plan.price}/{plan.billing_period}"
                )

        # Create yearly versions with 20% discount
        self.stdout.write("\nCreating yearly billing options...")
        for plan_data in plans_data:
            if plan_data["slug"] != "starter":  # Skip free plan for yearly
                # Get original plan features before creating yearly plan
                monthly_plan = SubscriptionPlan.objects.get(slug=plan_data["slug"])
                original_features = list(monthly_plan.features.values_list("code", flat=True))

                # Create yearly plan data
                yearly_plan_data = {
                    "name": plan_data["name"],
                    "slug": f"{plan_data['slug']}-yearly",
                    "description": plan_data["description"],
                    "price": float(plan_data["price"]) * 12 * 0.8,  # 20% discount
                    "currency": plan_data["currency"],
                    "billing_period": "yearly",
                    "max_stores": plan_data["max_stores"],
                    "max_users": plan_data["max_users"],
                    "max_products": plan_data["max_products"],
                    "max_orders_per_month": plan_data["max_orders_per_month"],
                    "max_warehouses": plan_data["max_warehouses"],
                    "trial_days": plan_data["trial_days"],
                    "sort_order": plan_data["sort_order"] + 10,
                }

                yearly_plan, created = SubscriptionPlan.objects.get_or_create(
                    slug=yearly_plan_data["slug"], defaults=yearly_plan_data
                )

                # Update yearly plan if it exists
                if not created:
                    for key, value in yearly_plan_data.items():
                        setattr(yearly_plan, key, value)
                    yearly_plan.save()

                # Associate features
                yearly_plan.features.clear()
                for feature_code in original_features:
                    if feature_code in features:
                        yearly_plan.features.add(features[feature_code])

                status = "Created" if created else "Updated"
                self.stdout.write(
                    f"  {status}: {yearly_plan.name} (Yearly) - {yearly_plan.currency}{yearly_plan.price}/{yearly_plan.billing_period}"
                )

                # Update yearly plan if it exists
                if not created:
                    for key, value in yearly_plan_data.items():
                        setattr(yearly_plan, key, value)
                    yearly_plan.save()

                # Associate features
                yearly_plan.features.clear()
                for feature_code in plan_features:
                    if feature_code in features:
                        yearly_plan.features.add(features[feature_code])

                status = "Created" if created else "Updated"
                self.stdout.write(
                    f"  {status}: {yearly_plan.name} (Yearly) - {yearly_plan.currency}{yearly_plan.price}/{yearly_plan.billing_period}"
                )

                # Update yearly plan if it exists
                if not created:
                    for key, value in yearly_plan_data.items():
                        setattr(yearly_plan, key, value)
                    yearly_plan.save()

                # Associate features
                yearly_plan.features.clear()
                for feature_code in plan_features:
                    if feature_code in features:
                        yearly_plan.features.add(features[feature_code])

                status = "Created" if created else "Updated"
                self.stdout.write(
                    f"  {status}: {yearly_plan.name} (Yearly) - {yearly_plan.currency}{yearly_plan.price}/{yearly_plan.billing_period}"
                )

        self.stdout.write(self.style.SUCCESS("\n✅ Subscription plans created successfully!"))
        self.stdout.write(f"Total features: {Feature.objects.count()}")
        self.stdout.write(f"Total plans: {SubscriptionPlan.objects.count()}")
