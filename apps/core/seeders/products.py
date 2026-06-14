"""
Products Seeder - Seeds product data.

This seeder creates/updates products based on defined data.
Add your products to the PRODUCTS_DATA list and run the seeder.

Usage:
    python manage.py seed products
"""

from typing import List, Dict, Any
from apps.core.seeders.base import BaseSeeder
from apps.stores.models import Store


class ProductSeeder(BaseSeeder):
    """Seeder for creating/updating product data from defined data."""

    description = "Creates/updates products from defined data"

    # Define your products here
    # lookup_field will be 'sku' - unique product identifier
    PRODUCTS_DATA: List[Dict[str, Any]] = [
        {
            "sku": "FASH-001",
            "name": "Classic Cotton T-Shirt",
            "store_slug": "fashion-hub",
            "description": "Comfortable 100% cotton t-shirt",
            "price": "29.99",
            "category": "Clothing",
            "stock": 100,
        },
        {
            "sku": "FASH-002",
            "name": "Denim Jeans",
            "store_slug": "fashion-hub",
            "description": "Classic fit denim jeans",
            "price": "59.99",
            "category": "Clothing",
            "stock": 50,
        },
        {
            "sku": "TECH-001",
            "name": "Wireless Headphones",
            "store_slug": "tech-haven",
            "description": "Bluetooth over-ear headphones",
            "price": "89.99",
            "category": "Electronics",
            "stock": 30,
        },
        # Add more products as needed
    ]

    def run(self):
        """Run the products seeder."""
        self.log("Starting product data seeding...")

        # Check if product models exist
        try:
            from apps.products.models import Product
        except ImportError:
            self.log("⚠️ Product models not yet implemented. Skipping product seeding.")
            self.log("   Implement this seeder after product models are created.")
            return

        created_count = 0
        updated_count = 0

        for product_data in self.PRODUCTS_DATA:
            sku = product_data["sku"]
            store_slug = product_data.pop("store_slug", None)

            # Get store
            if not store_slug:
                self.log(f"⚠️ Product {sku} has no store_slug")
                continue

            try:
                store = Store.objects.get(slug=store_slug)
            except Store.DoesNotExist:
                self.log(f"⚠️ Store not found: {store_slug}")
                continue

            product_data["store"] = store

            # Try to get existing product
            try:
                product = Product.objects.get(sku=sku)
                updated = False

                # Update existing product fields
                for field, value in product_data.items():
                    if field == "sku":
                        continue
                    if getattr(product, field, None) != value:
                        setattr(product, field, value)
                        updated = True

                if updated:
                    product.save()
                    updated_count += 1
                    self.log(f"✏️ Updated product: {sku}")
                else:
                    self.log(f"⊘ Product unchanged: {sku}")

            except Product.DoesNotExist:
                # Create new product
                Product.objects.create(**product_data)
                created_count += 1
                self.log(f"➕ Created product: {sku}")

        self.log(f"✅ Completed: {created_count} created, {updated_count} updated")
