"""
Customers Seeder - Seeds customer data.

This seeder creates/updates customers based on defined data.
Add your customers to the CUSTOMERS_DATA list and run the seeder.

Usage:
    python manage.py seed customers
"""

from typing import List, Dict, Any
from apps.core.seeders.base import BaseSeeder
from apps.accounts.models import User


class CustomerSeeder(BaseSeeder):
    """Seeder for creating/updating customer data from defined data."""

    description = "Creates/updates customer data from defined data"

    # Define your customers here
    # lookup_field will be 'email' - links to User model
    CUSTOMERS_DATA: List[Dict[str, Any]] = [
        {
            "email": "customer.one@email.com",
            "phone": "+1234567895",
            "address": "123 Main St, City, State, 12345",
            "notes": "VIP customer",
        },
        {
            "email": "customer.two@email.com",
            "phone": "+1234567896",
            "address": "456 Oak Ave, City, State, 12346",
            "notes": "Prefers email contact",
        },
        # Add more customers as needed
    ]

    def run(self):
        """Run the customers seeder."""
        self.log("Starting customer data seeding...")

        # Check if customer models exist
        try:
            from apps.customers.models import Customer
        except ImportError:
            self.log("⚠️ Customer models not yet implemented. Skipping customer seeding.")
            self.log("   Implement this seeder after customer models are created.")
            return

        created_count = 0
        updated_count = 0

        for customer_data in self.CUSTOMERS_DATA:
            email = customer_data["email"]

            # Verify user exists
            try:
                user = User.objects.get(email=email, role=User.UserRole.CUSTOMER)
            except User.DoesNotExist:
                self.log(f"⚠️ Customer user not found: {email}")
                continue

            # Try to get existing customer
            try:
                customer = Customer.objects.get(user=user)
                updated = False

                # Update existing customer fields
                for field, value in customer_data.items():
                    if field == "email":
                        continue
                    if getattr(customer, field, None) != value:
                        setattr(customer, field, value)
                        updated = True

                if updated:
                    customer.save()
                    updated_count += 1
                    self.log(f"✏️ Updated customer: {email}")
                else:
                    self.log(f"⊘ Customer unchanged: {email}")

            except Customer.DoesNotExist:
                # Create new customer
                customer_data["user"] = user
                Customer.objects.create(**customer_data)
                created_count += 1
                self.log(f"➕ Created customer: {email}")

        self.log(f"✅ Completed: {created_count} created, {updated_count} updated")
