"""
Accounts Seeder - Seeds User accounts.

This seeder creates/updates users based on defined data.
Add your users to the USERS_DATA list and run the seeder.

Usage:
    python manage.py seed accounts
"""

from typing import List, Dict, Any
from apps.core.seeders.base import BaseSeeder
from apps.accounts.models import User


class AccountSeeder(BaseSeeder):
    """Seeder for creating/updating user accounts from defined data."""

    description = "Creates/updates user accounts from defined data"

    # Default password for all users (can be overridden per user)
    DEFAULT_PASSWORD = "Demo@123456"

    # Define your users here
    # lookup_field is 'email' - will be used to find existing users
    USERS_DATA: List[Dict[str, Any]] = [
        # Admin user
        {
            "email": "admin@socialcrm.demo",
            "first_name": "Super",
            "last_name": "Admin",
            "role": User.UserRole.ADMIN,
            "is_staff": True,
            "is_superuser": True,
            "is_active": True,
            "email_verified": True,
            "phone_verified": True,
            "password": DEFAULT_PASSWORD,
        },
        # Store Owners
        {
            "email": "john.doe@store.com",
            "first_name": "John",
            "last_name": "Doe",
            "phone_number": "+1234567890",
            "role": User.UserRole.STORE_OWNER,
            "is_active": True,
            "email_verified": True,
            "password": DEFAULT_PASSWORD,
        },
        {
            "email": "jane.smith@store.com",
            "first_name": "Jane",
            "last_name": "Smith",
            "phone_number": "+1234567891",
            "role": User.UserRole.STORE_OWNER,
            "is_active": True,
            "email_verified": True,
            "password": DEFAULT_PASSWORD,
        },
        # Store Managers
        {
            "email": "mike.wilson@store.com",
            "first_name": "Mike",
            "last_name": "Wilson",
            "phone_number": "+1234567892",
            "role": User.UserRole.STORE_MANAGER,
            "is_active": True,
            "email_verified": True,
            "password": DEFAULT_PASSWORD,
        },
        # Store Staff
        {
            "email": "sarah.jones@store.com",
            "first_name": "Sarah",
            "last_name": "Jones",
            "phone_number": "+1234567893",
            "role": User.UserRole.STORE_STAFF,
            "is_active": True,
            "email_verified": True,
            "password": DEFAULT_PASSWORD,
        },
        {
            "email": "tom.brown@store.com",
            "first_name": "Tom",
            "last_name": "Brown",
            "phone_number": "+1234567894",
            "role": User.UserRole.STORE_STAFF,
            "is_active": True,
            "email_verified": True,
            "password": DEFAULT_PASSWORD,
        },
        # Customers
        {
            "email": "customer.one@email.com",
            "first_name": "Alice",
            "last_name": "Johnson",
            "phone_number": "+1234567895",
            "role": User.UserRole.CUSTOMER,
            "is_active": True,
            "email_verified": True,
            "password": DEFAULT_PASSWORD,
        },
        {
            "email": "customer.two@email.com",
            "first_name": "Bob",
            "last_name": "Miller",
            "phone_number": "+1234567896",
            "role": User.UserRole.CUSTOMER,
            "is_active": True,
            "email_verified": False,
            "password": DEFAULT_PASSWORD,
        },
    ]

    def run(self):
        """Run the accounts seeder."""
        self.log("Starting user account seeding...")

        created_count = 0
        updated_count = 0

        for user_data in self.USERS_DATA:
            email = user_data["email"]
            password = user_data.pop("password", self.DEFAULT_PASSWORD)

            # Try to get existing user
            try:
                user = User.objects.get(email=email)
                updated = False

                # Update existing user fields
                for field, value in user_data.items():
                    if field == "email":
                        continue
                    if getattr(user, field) != value:
                        setattr(user, field, value)
                        updated = True

                if updated:
                    user.save()
                    # Update password if provided
                    if password:
                        user.set_password(password)
                        user.save(update_fields=["password"])
                    updated_count += 1
                    self.log(f"✏️ Updated user: {email}")
                else:
                    self.log(f"⊘ User unchanged: {email}")

            except User.DoesNotExist:
                # Create new user
                user = User.objects.create(**user_data)
                user.set_password(password)
                user.save()
                created_count += 1
                self.log(f"➕ Created user: {email}")

        self.log(f"✅ Completed: {created_count} created, {updated_count} updated")
