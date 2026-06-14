# Seeder System Guide

## Overview

The Social Commerce CRM includes a comprehensive seeder system for populating your database with defined data. This system allows you to define your data explicitly in code, then run seeders to insert or update that data. Perfect for development, testing, and maintaining consistent baseline data.

## Features

- **Defined Data Pattern**: Define your data explicitly in code (no random/fake data)
- **Insert or Update**: Seeders will insert new records or update existing ones
- **Idempotent**: Running seeders multiple times is safe and produces consistent results
- **Relationship Support**: Handles many-to-many relationships automatically
- **Transaction Safety**: Each seeder runs within a database transaction

## Usage

### Basic Commands

```bash
# List all available seeders
python manage.py seed --list

# Run all seeders
python manage.py seed

# Run a specific seeder
python manage.py seed accounts
python manage.py seed stores

# Run multiple seeders
python manage.py seed accounts stores customers

# Clear all data before seeding (WARNING: deletes all data)
python manage.py seed --flush

# Silent mode (no output)
python manage.py seed --seed-verbosity=0

# Verbose mode (detailed output)
python manage.py seed --seed-verbosity=2
```

## Available Seeders

### Accounts Seeder

Creates/updates user accounts from defined data.

**File**: [apps/core/seeders/accounts.py](../apps/core/seeders/accounts.py)

**Usage**:
```python
from apps.core.seeders.accounts import AccountSeeder

# Define your users in the USERS_DATA list
USERS_DATA = [
    {
        "email": "user@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "role": User.UserRole.CUSTOMER,
        "password": "YourPassword123",
    },
    # Add more users...
]
```

**Run**:
```bash
python manage.py seed accounts
```

### Stores Seeder

Creates/updates stores and their relationships.

**File**: [apps/core/seeders/stores.py](../apps/core/seeders/stores.py)

**Usage**:
```python
from apps.core.seeders.stores import StoreSeeder

# Define your stores in the STORES_DATA list
STORES_DATA = [
    {
        "name": "My Store",
        "slug": "my-store",
        "description": "Store description",
        "status": "active",
        "settings": {"currency": "USD"},
        "owners_emails": ["owner@example.com"],
        "managers_emails": ["manager@example.com"],
        "staff_emails": ["staff1@example.com", "staff2@example.com"],
    },
    # Add more stores...
]
```

**Run**:
```bash
python manage.py seed stores
```

### Products Seeder (Placeholder)

Ready for implementation when product models exist.

**File**: [apps/core/seeders/products.py](../apps/core/seeders/products.py)

### Customers Seeder (Placeholder)

Ready for implementation when customer models exist.

**File**: [apps/core/seeders/customers.py](../apps/core/seeders/customers.py)

### Orders Seeder (Placeholder)

Ready for implementation when order models exist.

**File**: [apps/core/seeders/orders.py](../apps/core/seeders/orders.py)

## Creating a New Seeder

### Step 1: Create the Seeder Module

Create a new file in `apps/core/seeders/`:

```python
from typing import List, Dict, Any
from apps.core.seeders.base import BaseSeeder

class MyModelSeeder(BaseSeeder):
    """Seeder for creating/updating myapp data."""

    description = "Creates/updates myapp data from defined data"

    # Define your data here
    MY_DATA: List[Dict[str, Any]] = [
        {
            "lookup_field": "unique_value",
            "field1": "value1",
            "field2": "value2",
        },
        # Add more items...
    ]

    def run(self):
        """Run the seeder."""
        from myapp.models import MyModel

        self.log("Starting myapp seeding...")

        created_count = 0
        updated_count = 0

        for item_data in self.MY_DATA:
            lookup_value = item_data["lookup_field"]

            # Try to get existing record
            try:
                instance = MyModel.objects.get(lookup_field=lookup_value)
                updated = False

                # Update fields that changed
                for field, value in item_data.items():
                    if field == "lookup_field":
                        continue
                    if getattr(instance, field, None) != value:
                        setattr(instance, field, value)
                        updated = True

                if updated:
                    instance.save()
                    updated_count += 1
                    self.log(f"✏️ Updated: {lookup_value}")
                else:
                    self.log(f"⊘ Unchanged: {lookup_value}")

            except MyModel.DoesNotExist:
                # Create new record
                MyModel.objects.create(**item_data)
                created_count += 1
                self.log(f"➕ Created: {lookup_value}")

        self.log(f"✅ Completed: {created_count} created, {updated_count} updated")
```

### Step 2: Register the Seeder

Add your seeder to `apps/core/seeders/__init__.py`:

```python
def get_all_seeders():
    """Get all registered seeders."""
    from . import accounts
    from . import stores
    from . import myapp  # Add this

    return {
        "accounts": accounts.AccountSeeder,
        "stores": stores.StoreSeeder,
        "myapp": myapp.MyModelSeeder,  # Add this
    }
```

### Step 3: Run Your Seeder

```bash
python manage.py seed myapp
```

## Examples

### Example 1: Simple Seeder

```python
from typing import List, Dict, Any
from apps.core.seeders.base import BaseSeeder
from apps.myapp.models import Category

class CategorySeeder(BaseSeeder):
    description = "Creates/updates categories"

    CATEGORIES_DATA: List[Dict[str, Any]] = [
        {
            "name": "Electronics",
            "description": "Electronic products",
        },
        {
            "name": "Clothing",
            "description": "Clothing and accessories",
        },
    ]

    def run(self):
        created_count = 0
        updated_count = 0

        for cat_data in self.CATEGORIES_DATA:
            name = cat_data["name"]

            try:
                category = Category.objects.get(name=name)
                # Update if changed
                if category.description != cat_data["description"]:
                    category.description = cat_data["description"]
                    category.save()
                    updated_count += 1
            except Category.DoesNotExist:
                Category.objects.create(**cat_data)
                created_count += 1

        self.log(f"✅ Completed: {created_count} created, {updated_count} updated")
```

### Example 2: Seeder with Relationships

```python
from typing import List, Dict, Any
from apps.core.seeders.base import BaseSeeder
from apps.myapp.models import Product
from apps.stores.models import Store

class ProductSeeder(BaseSeeder):
    description = "Creates/updates products"

    PRODUCTS_DATA: List[Dict[str, Any]] = [
        {
            "sku": "PROD-001",
            "name": "Product Name",
            "store_slug": "my-store",
            "price": "29.99",
        },
    ]

    def run(self):
        created_count = 0
        updated_count = 0

        for product_data in self.PRODUCTS_DATA:
            sku = product_data["sku"]
            store_slug = product_data.pop("store_slug")

            # Get related store
            try:
                store = Store.objects.get(slug=store_slug)
            except Store.DoesNotExist:
                self.log(f"⚠️ Store not found: {store_slug}")
                continue

            product_data["store"] = store

            # Create or update product
            try:
                product = Product.objects.get(sku=sku)
                # Update logic here...
                updated_count += 1
            except Product.DoesNotExist:
                Product.objects.create(**product_data)
                created_count += 1

        self.log(f"✅ Completed: {created_count} created, {updated_count} updated")
```

## Best Practices

1. **Define Data Explicitly**: All data should be defined in the `*_DATA` list
2. **Use Unique Lookup Fields**: Choose a field that uniquely identifies each record
3. **Handle Missing Relations**: Check if related objects exist before creating
4. **Use Meaningful Identifiers**: Use readable IDs like `sku`, `email`, `slug`
5. **Log Changes**: Use clear log messages to track what changed
6. **Idempotent by Design**: Running multiple times should produce same result

## Output Symbols

- `➕` - Created new record
- `✏️` - Updated existing record
- `⊘` - Unchanged (no updates needed)
- `→` - Added relationship
- `←` - Removed relationship
- `⚠️` - Warning (missing data, etc.)
- `❌` - Error occurred

## File Structure

```
apps/core/
├── management/
│   └── commands/
│       └── seed.py              # Django management command
└── seeders/
    ├── __init__.py              # Central registry
    ├── base.py                  # Base seeder class
    ├── accounts.py              # Accounts seeder (functional)
    ├── stores.py                # Stores seeder (functional)
    ├── customers.py             # Customers seeder (placeholder)
    ├── products.py              # Products seeder (placeholder)
    └── orders.py                # Orders seeder (placeholder)
```

## Troubleshooting

### Seeder Not Found

```bash
# Check available seeders
python manage.py seed --list
```

### Import Errors

Ensure:
1. The seeder module exists in `apps/core/seeders/`
2. The seeder is registered in `get_all_seeders()`
3. All imports are correct

### Relationship Errors

If relationships fail:
1. Run dependent seeders first
2. Check that related records exist
3. Verify lookup field values are correct
