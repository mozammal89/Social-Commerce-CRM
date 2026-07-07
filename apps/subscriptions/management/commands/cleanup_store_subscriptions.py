"""
Django management command to clean up legacy store-based subscriptions.

This removes store-level subscriptions that interfere with tenant-based subscription architecture.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
import logging

from apps.stores.models import Store
from apps.subscriptions.models import Subscription
from apps.accounts.models import Tenant

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Remove interfering store-based subscriptions and consolidate to tenant-based architecture"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Run without making changes",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            dest="force",
            help="Force cleanup even if subscriptions are active",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        force = options.get("force", False)

        self.stdout.write(self.style.SUCCESS("Starting store subscription cleanup..."))

        interfering_stores = self.find_interfering_subscriptions()

        if not interfering_stores:
            self.stdout.write(self.style.SUCCESS("✅ No interfering subscriptions found!"))
            return

        self.stdout.write(f"\nFound {len(interfering_stores)} interfering subscriptions:\n")

        for item in interfering_stores:
            self.stdout.write(f"• {item['store']} (Tenant: {item['tenant']})")
            self.stdout.write(f"  Store sub: {item['store_plan']} ({item['store_status']})")
            self.stdout.write(f"  Tenant sub: {item['tenant_plan']} ({item['tenant_status']})")
            self.stdout.write(f"  Issue: {item['issue']}")
            self.stdout.write()

        if not force:
            self.stdout.write(
                self.style.WARNING("\n⚠️  Use --force to delete these store subscriptions")
            )
            self.stdout.write(
                self.style.WARNING("This will force all stores to use tenant subscriptions")
            )
            return

        try:
            self.cleanup_subscriptions(interfering_stores, dry_run=dry_run)
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Cleanup failed: {str(e)}"))
            raise

    def find_interfering_subscriptions(self):
        """Find all stores with subscriptions that differ from their tenant subscription."""
        interfering_stores = []

        for store in Store.objects.filter(subscription__isnull=False, tenant__isnull=False):
            tenant = store.tenant
            store_sub = store.subscription

            if not tenant or not hasattr(tenant, "subscription") or not tenant.subscription:
                # Store has subscription but tenant doesn't - mark as interfering
                interfering_stores.append(
                    {
                        "store": store.name,
                        "store_id": store.id,
                        "store_sub_id": store_sub.id,
                        "tenant": tenant.name if tenant else "No tenant",
                        "store_plan": store_sub.plan.name,
                        "store_status": store_sub.status,
                        "tenant_plan": "No tenant subscription",
                        "tenant_status": "N/A",
                        "issue": "NO_TENANT_SUBSCRIPTION",
                    }
                )
                continue

            tenant_sub = tenant.subscription

            # Check if they're different
            if store_sub.id != tenant_sub.id:
                interfering_stores.append(
                    {
                        "store": store.name,
                        "store_id": store.id,
                        "store_sub_id": store_sub.id,
                        "tenant": tenant.name,
                        "store_plan": store_sub.plan.name,
                        "store_status": store_sub.status,
                        "tenant_plan": tenant_sub.plan.name,
                        "tenant_status": tenant_sub.status,
                        "issue": "DIFFERENT_PLANS",
                    }
                )
            elif store_sub.status != tenant_sub.status:
                interfering_stores.append(
                    {
                        "store": store.name,
                        "store_id": store.id,
                        "store_sub_id": store_sub.id,
                        "tenant": tenant.name,
                        "store_plan": store_sub.plan.name,
                        "store_status": store_sub.status,
                        "tenant_plan": tenant_sub.plan.name,
                        "tenant_status": tenant_sub.status,
                        "issue": "DIFFERENT_STATUS",
                    }
                )

        return interfering_stores

    def cleanup_subscriptions(self, interfering_stores, dry_run=False):
        """Remove interfering store subscriptions."""

        with transaction.atomic():
            for item in interfering_stores:
                store_id = item["store_id"]
                store_sub_id = item["store_sub_id"]
                issue = item["issue"]

                if issue == "NO_TENANT_SUBSCRIPTION":
                    # This shouldn't happen after migration, but handle it
                    self.stdout.write(
                        self.style.WARNING(f"Skipping {item['store']} - no tenant subscription")
                    )
                    continue

                self.stdout.write(f"Removing store subscription for: {item['store']}")

                if not dry_run:
                    # Delete the store subscription
                    Subscription.objects.filter(id=store_sub_id).delete()
                    self.stdout.write(f"  ✓ Deleted store subscription")
                else:
                    self.stdout.write(f"  [DRY RUN] Would delete store subscription")

            if dry_run:
                self.stdout.write(self.style.WARNING("\nDRY RUN - No changes were made"))
                transaction.set_rollback(True)
            else:
                self.stdout.write(self.style.SUCCESS("\n✅ Cleanup completed successfully!"))
                self.stdout.write(
                    f"Removed {len(interfering_stores)} interfering store subscriptions"
                )
                self.stdout.write("\nAll stores will now use tenant subscriptions")
