"""
Orders Seeder - Seeds order data.

This seeder creates/updates orders based on defined data.
Add your orders to the ORDERS_DATA list and run the seeder.

Usage:
    python manage.py seed orders
"""

from typing import List, Dict, Any
from apps.core.seeders.base import BaseSeeder
from apps.accounts.models import User
from apps.stores.models import Store


class OrderSeeder(BaseSeeder):
    """Seeder for creating/updating order data from defined data."""

    description = "Creates/updates orders from defined data"

    # Define your orders here
    # lookup_field will be 'order_number' - unique order identifier
    ORDERS_DATA: List[Dict[str, Any]] = [
        {
            "order_number": "ORD-2024-001",
            "customer_email": "customer.one@email.com",
            "store_slug": "fashion-hub",
            "status": "completed",
            "total_amount": "89.97",
            "notes": "Express delivery requested",
        },
        {
            "order_number": "ORD-2024-002",
            "customer_email": "customer.two@email.com",
            "store_slug": "tech-haven",
            "status": "pending",
            "total_amount": "89.99",
            "notes": "Gift wrap required",
        },
        # Add more orders as needed
    ]

    def run(self):
        """Run the orders seeder."""
        self.log("Starting order data seeding...")

        # Check if order models exist
        try:
            from apps.orders.models import Order
        except ImportError:
            self.log("⚠️ Order models not yet implemented. Skipping order seeding.")
            self.log("   Implement this seeder after order models are created.")
            return

        created_count = 0
        updated_count = 0

        for order_data in self.ORDERS_DATA:
            order_number = order_data["order_number"]
            customer_email = order_data.pop("customer_email", None)
            store_slug = order_data.pop("store_slug", None)

            # Get customer
            if not customer_email:
                self.log(f"⚠️ Order {order_number} has no customer_email")
                continue

            try:
                customer = User.objects.get(
                    email=customer_email, role=User.UserRole.CUSTOMER
                )
            except User.DoesNotExist:
                self.log(f"⚠️ Customer not found: {customer_email}")
                continue

            # Get store
            if not store_slug:
                self.log(f"⚠️ Order {order_number} has no store_slug")
                continue

            try:
                store = Store.objects.get(slug=store_slug)
            except Store.DoesNotExist:
                self.log(f"⚠️ Store not found: {store_slug}")
                continue

            order_data["customer"] = customer
            order_data["store"] = store

            # Try to get existing order
            try:
                order = Order.objects.get(order_number=order_number)
                updated = False

                # Update existing order fields
                for field, value in order_data.items():
                    if field in ["order_number", "customer_email", "store_slug"]:
                        continue
                    if getattr(order, field, None) != value:
                        setattr(order, field, value)
                        updated = True

                if updated:
                    order.save()
                    updated_count += 1
                    self.log(f"✏️ Updated order: {order_number}")
                else:
                    self.log(f"⊘ Order unchanged: {order_number}")

            except Order.DoesNotExist:
                # Create new order
                Order.objects.create(**order_data)
                created_count += 1
                self.log(f"➕ Created order: {order_number}")

        self.log(f"✅ Completed: {created_count} created, {updated_count} updated")
