"""
Django management command to migrate store-based subscriptions to tenant-based subscriptions.

This command safely creates tenants for existing store owners and migrates subscriptions.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
import logging

from apps.accounts.models import User, Tenant
from apps.stores.models import Store
from apps.permissions.models import Subscription

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Migrate store-based subscriptions to tenant-based subscriptions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Run migration without making changes",
        )
        parser.add_argument(
            "--verify",
            action="store_true",
            dest="verify",
            help="Verify existing migration",
        )

    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)
        verify = options.get("verify", False)

        if verify:
            self.verify_migration()
        else:
            self.migrate_subscriptions(dry_run=dry_run)

    def migrate_subscriptions(self, dry_run=False):
        """Migrate existing store-based subscriptions to tenant-based subscriptions."""

        self.stdout.write(
            self.style.SUCCESS(
                "Starting subscription migration from store-based to tenant-based architecture..."
            )
        )

        try:
            with transaction.atomic():
                # Step 1: Create tenants for existing store owners
                self.stdout.write("Step 1: Creating tenants for existing store owners...")
                store_owners = User.objects.filter(owned_stores__isnull=False).distinct()

                owner_to_tenant = {}
                for owner in store_owners:
                    # Create tenant for each store owner
                    tenant_slug = f"{owner.email.split('@')[0]}-workspace"
                    tenant, created = Tenant.objects.get_or_create(
                        slug=tenant_slug,
                        defaults={
                            "name": f"{owner.get_full_name()}'s Workspace",
                            "owner": owner,
                            "is_active": True,
                        },
                    )
                    if created:
                        self.stdout.write(
                            f"  Created tenant '{tenant.name}' for owner {owner.email}"
                        )
                    else:
                        self.stdout.write(
                            f"  Using existing tenant '{tenant.name}' for owner {owner.email}"
                        )

                    owner_to_tenant[owner.id] = tenant

                # Step 2: Link stores to their owner's tenant
                self.stdout.write("Step 2: Linking stores to their owner's tenant...")
                stores_updated = 0
                for store in Store.objects.filter(tenant__isnull=True):
                    # Get the first owner of the store
                    first_owner = store.owners.first()
                    if first_owner and first_owner.id in owner_to_tenant:
                        tenant = owner_to_tenant[first_owner.id]
                        if not dry_run:
                            store.tenant = tenant
                            store.save(update_fields=["tenant"])
                        stores_updated += 1
                        self.stdout.write(
                            f"  Linked store '{store.name}' to tenant '{tenant.name}'"
                        )
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  No tenant found for store '{store.name}' - skipping"
                            )
                        )

                self.stdout.write(f"  Linked {stores_updated} stores to tenants")

                # Step 3: Move subscriptions from stores to tenants
                self.stdout.write("Step 3: Moving subscriptions from stores to tenants...")
                subscriptions_migrated = 0
                subscriptions_skipped = 0

                for subscription in Subscription.objects.filter(
                    store__isnull=False, tenant__isnull=True
                ):
                    store = subscription.store
                    if store.tenant:
                        # Check if tenant already has a subscription
                        try:
                            existing_tenant_subscription = Subscription.objects.get(
                                tenant=store.tenant
                            )
                            # Tenant already has a subscription, skip this one
                            subscriptions_skipped += 1
                            self.stdout.write(
                                f"  Skipped subscription for store '{store.name}' - tenant already has subscription"
                            )
                        except Subscription.DoesNotExist:
                            # No tenant subscription yet, safe to migrate
                            if not dry_run:
                                subscription.tenant = store.tenant
                                subscription.save(update_fields=["tenant"])
                            subscriptions_migrated += 1
                            self.stdout.write(
                                f"  Moved subscription from store '{store.name}' to tenant '{store.tenant.name}'"
                            )
                    else:
                        self.stdout.write(
                            self.style.WARNING(
                                f"  Store '{store.name}' has no tenant - cannot migrate subscription"
                            )
                        )

                self.stdout.write(f"  Migrated {subscriptions_migrated} subscriptions to tenants")
                if subscriptions_skipped > 0:
                    self.stdout.write(
                        f"  Skipped {subscriptions_skipped} subscriptions (tenants already have subscriptions)"
                    )

                if dry_run:
                    self.stdout.write(self.style.WARNING("DRY RUN - No changes were made"))
                    transaction.set_rollback(True)
                else:
                    self.stdout.write(self.style.SUCCESS("✅ Migration completed successfully!"))
                    self.stdout.write(f"Summary:")
                    self.stdout.write(f"  - Tenants created/used: {len(owner_to_tenant)}")
                    self.stdout.write(f"  - Stores linked to tenants: {stores_updated}")
                    self.stdout.write(f"  - Subscriptions migrated: {subscriptions_migrated}")

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Migration failed: {str(e)}"))
            raise

    def verify_migration(self):
        """Verify that the migration was successful."""

        self.stdout.write("Verifying migration...")

        # Check that all stores have tenants
        stores_without_tenants = Store.objects.filter(tenant__isnull=True)
        if stores_without_tenants.exists():
            self.stdout.write(
                self.style.WARNING(f"Found {stores_without_tenants.count()} stores without tenants")
            )
            for store in stores_without_tenants:
                self.stdout.write(f"  - Store: {store.name} (ID: {store.id})")
        else:
            self.stdout.write(self.style.SUCCESS("✅ All stores have tenants"))

        # Check that all subscriptions have tenants
        subscriptions_without_tenants = Subscription.objects.filter(
            tenant__isnull=True, store__isnull=False
        )
        if subscriptions_without_tenants.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Found {subscriptions_without_tenants.count()} subscriptions without tenants"
                )
            )
            for subscription in subscriptions_without_tenants:
                self.stdout.write(f"  - Subscription ID: {subscription.id}")
        else:
            self.stdout.write(self.style.SUCCESS("✅ All active subscriptions have tenants"))

        # Check that each tenant has at most one subscription
        from django.db.models import Count

        tenants_with_multiple_subscriptions = Tenant.objects.annotate(
            sub_count=Count("subscription")
        ).filter(sub_count__gt=1)

        if tenants_with_multiple_subscriptions.exists():
            self.stdout.write(
                self.style.WARNING(
                    f"Found {tenants_with_multiple_subscriptions.count()} tenants with multiple subscriptions"
                )
            )
            for tenant in tenants_with_multiple_subscriptions:
                self.stdout.write(
                    f"  - Tenant: {tenant.name} (Subscription count: {tenant.sub_count})"
                )
        else:
            self.stdout.write(self.style.SUCCESS("✅ All tenants have at most one subscription"))

        # Check that all stores under the same tenant have the same subscription
        self.stdout.write("Checking subscription consistency across stores...")
        inconsistent_tenants = []
        for tenant in Tenant.objects.all():
            if tenant.stores.exists():
                subscriptions = set()
                for store in tenant.stores.all():
                    try:
                        if store.subscription:
                            subscriptions.add(store.subscription.id)
                    except Exception:
                        pass  # Store has no subscription, skip

                if len(subscriptions) > 1:
                    inconsistent_tenants.append(
                        {"tenant": tenant.name, "subscriptions": subscriptions}
                    )

        if inconsistent_tenants:
            self.stdout.write(
                self.style.WARNING(
                    f"Found {len(inconsistent_tenants)} tenants with inconsistent store subscriptions"
                )
            )
            for item in inconsistent_tenants:
                self.stdout.write(
                    f"  - Tenant: {item['tenant']} has subscriptions: {item['subscriptions']}"
                )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "✅ All stores under the same tenant have consistent subscriptions"
                )
            )
