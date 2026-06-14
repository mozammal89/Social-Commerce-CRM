"""
Stores Seeder - Seeds store data.

This seeder creates/updates stores based on defined data.
Add your stores to the STORES_DATA list and run the seeder.

Usage:
    python manage.py seed stores
"""

from typing import List, Dict, Any
from apps.core.seeders.base import BaseSeeder
from apps.stores.models import Store
from apps.accounts.models import User


class StoreSeeder(BaseSeeder):
    """Seeder for creating/updating stores from defined data."""

    description = "Creates/updates stores from defined data"

    # Define your stores here
    # lookup_field is 'name' - will be used to find existing stores
    STORES_DATA: List[Dict[str, Any]] = [
        {
            "name": "Fashion Hub",
            "slug": "fashion-hub",
            "description": "Your one-stop shop for trendy fashion and accessories.",
            "status": "active",
            "settings": {
                "currency": "USD",
                "timezone": "UTC",
                "language": "en",
            },
            "owners_emails": ["john.doe@store.com"],
            "managers_emails": ["mike.wilson@store.com"],
            "staff_emails": ["sarah.jones@store.com", "tom.brown@store.com"],
        },
        {
            "name": "Tech Haven",
            "slug": "tech-haven",
            "description": "Latest electronics and gadgets for tech enthusiasts.",
            "status": "active",
            "settings": {
                "currency": "USD",
                "timezone": "UTC",
                "language": "en",
            },
            "owners_emails": ["jane.smith@store.com"],
            "managers_emails": ["mike.wilson@store.com"],
            "staff_emails": ["sarah.jones@store.com"],
        },
    ]

    def run(self):
        """Run the stores seeder."""
        self.log("Starting store seeding...")

        created_count = 0
        updated_count = 0

        for store_data in self.STORES_DATA:
            name = store_data["name"]

            # Extract relationship emails
            owners_emails = store_data.pop("owners_emails", [])
            managers_emails = store_data.pop("managers_emails", [])
            staff_emails = store_data.pop("staff_emails", [])

            # Try to get existing store
            try:
                store = Store.objects.get(name=name)
                updated = False

                # Update existing store fields
                for field, value in store_data.items():
                    if field == "name":
                        continue
                    current_value = getattr(store, field)
                    if current_value != value:
                        setattr(store, field, value)
                        updated = True

                if updated:
                    store.save()
                    updated_count += 1
                    self.log(f"✏️ Updated store: {name}")
                else:
                    self.log(f"⊘ Store unchanged: {name}")

            except Store.DoesNotExist:
                # Create new store
                store = Store.objects.create(**store_data)
                created_count += 1
                self.log(f"➕ Created store: {name}")

            # Update relationships
            self._update_owners(store, owners_emails)
            self._update_managers(store, managers_emails)
            self._update_staff(store, staff_emails)

        self.log(f"✅ Completed: {created_count} created, {updated_count} updated")

    def _update_owners(self, store: Store, emails: List[str]):
        """Update store owners."""
        current_owners = set(store.owners.values_list("email", flat=True))
        new_owners = set(emails)

        # Add new owners
        for email in new_owners - current_owners:
            try:
                user = User.objects.get(email=email)
                store.owners.add(user)
                self.log(f"  → Added owner: {email}")
            except User.DoesNotExist:
                self.log(f"  ⚠️ Owner not found: {email}")

        # Remove removed owners
        for email in current_owners - new_owners:
            try:
                user = User.objects.get(email=email)
                store.owners.remove(user)
                self.log(f"  ← Removed owner: {email}")
            except User.DoesNotExist:
                pass

    def _update_managers(self, store: Store, emails: List[str]):
        """Update store managers."""
        current_managers = set(store.managers.values_list("email", flat=True))
        new_managers = set(emails)

        for email in new_managers - current_managers:
            try:
                user = User.objects.get(email=email)
                store.managers.add(user)
                self.log(f"  → Added manager: {email}")
            except User.DoesNotExist:
                self.log(f"  ⚠️ Manager not found: {email}")

        for email in current_managers - new_managers:
            try:
                user = User.objects.get(email=email)
                store.managers.remove(user)
                self.log(f"  ← Removed manager: {email}")
            except User.DoesNotExist:
                pass

    def _update_staff(self, store: Store, emails: List[str]):
        """Update store staff."""
        current_staff = set(store.staff.values_list("email", flat=True))
        new_staff = set(emails)

        for email in new_staff - current_staff:
            try:
                user = User.objects.get(email=email)
                store.staff.add(user)
                self.log(f"  → Added staff: {email}")
            except User.DoesNotExist:
                self.log(f"  ⚠️ Staff not found: {email}")

        for email in current_staff - new_staff:
            try:
                user = User.objects.get(email=email)
                store.staff.remove(user)
                self.log(f"  ← Removed staff: {email}")
            except User.DoesNotExist:
                pass
