"""
Data migration script to convert store-based subscriptions to tenant-based subscriptions.

This script handles the migration of existing subscriptions from the store-based architecture
to the tenant-based architecture safely and efficiently.

Migration strategy:
1. Create one tenant per store owner
2. Link each store to its owner's tenant
3. Move subscriptions from stores to tenants
4. Update all related services and validations

Run this script after applying the database migrations for the Tenant model.
"""

import django
import logging
from django.db import transaction
from django.utils import timezone

# Setup Django
django.setup()

from apps.accounts.models import User, Tenant
from apps.stores.models import Store
from apps.permissions.models import Subscription

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def migrate_subscriptions_to_tenants():
    """Migrate existing store-based subscriptions to tenant-based subscriptions."""

    logger.info("Starting subscription migration from store-based to tenant-based architecture...")

    try:
        with transaction.atomic():
            # Step 1: Create tenants for existing store owners
            logger.info("Step 1: Creating tenants for existing store owners...")
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
                    logger.info(f"Created tenant '{tenant.name}' for owner {owner.email}")
                else:
                    logger.info(f"Using existing tenant '{tenant.name}' for owner {owner.email}")

                owner_to_tenant[owner.id] = tenant

            # Step 2: Link stores to their owner's tenant
            logger.info("Step 2: Linking stores to their owner's tenant...")
            stores_updated = 0
            for store in Store.objects.filter(tenant__isnull=True):
                # Get the first owner of the store
                first_owner = store.owners.first()
                if first_owner and first_owner.id in owner_to_tenant:
                    tenant = owner_to_tenant[first_owner.id]
                    store.tenant = tenant
                    store.save(update_fields=["tenant"])
                    stores_updated += 1
                    logger.info(f"Linked store '{store.name}' to tenant '{tenant.name}'")
                else:
                    logger.warning(f"No tenant found for store '{store.name}' - skipping")

            logger.info(f"Linked {stores_updated} stores to tenants")

            # Step 3: Move subscriptions from stores to tenants
            logger.info("Step 3: Moving subscriptions from stores to tenants...")
            subscriptions_migrated = 0
            for subscription in Subscription.objects.filter(
                store__isnull=False, tenant__isnull=True
            ):
                store = subscription.store
                if store.tenant:
                    subscription.tenant = store.tenant
                    subscription.save(update_fields=["tenant"])
                    subscriptions_migrated += 1
                    logger.info(
                        f"Moved subscription from store '{store.name}' to tenant '{store.tenant.name}'"
                    )
                else:
                    logger.warning(
                        f"Store '{store.name}' has no tenant - cannot migrate subscription"
                    )

            logger.info(f"Migrated {subscriptions_migrated} subscriptions to tenants")

            # Step 4: Update subscription events to reference tenant
            logger.info("Step 4: Updating subscription events to reference tenant...")
            from apps.permissions.models import SubscriptionEvent

            # Note: Subscription events already reference subscription, so they should work correctly
            # after the subscription migration. No additional action needed.
            logger.info(
                "Subscription events will automatically reference the correct tenant through subscription"
            )

            logger.info("✅ Migration completed successfully!")
            logger.info(f"Summary:")
            logger.info(f"  - Tenants created: {len(owner_to_tenant)}")
            logger.info(f"  - Stores linked to tenants: {stores_updated}")
            logger.info(f"  - Subscriptions migrated: {subscriptions_migrated}")

    except Exception as e:
        logger.error(f"❌ Migration failed: {str(e)}")
        raise


def verify_migration():
    """Verify that the migration was successful."""

    logger.info("Verifying migration...")

    # Check that all stores have tenants
    stores_without_tenants = Store.objects.filter(tenant__isnull=True)
    if stores_without_tenants.exists():
        logger.warning(f"Found {stores_without_tenants.count()} stores without tenants")
        for store in stores_without_tenants:
            logger.warning(f"  - Store: {store.name} (ID: {store.id})")
    else:
        logger.info("✅ All stores have tenants")

    # Check that all subscriptions have tenants
    subscriptions_without_tenants = Subscription.objects.filter(
        tenant__isnull=True, store__isnull=False
    )
    if subscriptions_without_tenants.exists():
        logger.warning(
            f"Found {subscriptions_without_tenants.count()} subscriptions without tenants"
        )
        for subscription in subscriptions_without_tenants:
            logger.warning(f"  - Subscription ID: {subscription.id}")
    else:
        logger.info("✅ All active subscriptions have tenants")

    # Check that each tenant has at most one subscription
    from django.db.models import Count

    tenants_with_multiple_subscriptions = Tenant.objects.annotate(
        sub_count=Count("subscription")
    ).filter(sub_count__gt=1)

    if tenants_with_multiple_subscriptions.exists():
        logger.warning(
            f"Found {tenants_with_multiple_subscriptions.count()} tenants with multiple subscriptions"
        )
        for tenant in tenants_with_multiple_subscriptions:
            logger.warning(f"  - Tenant: {tenant.name} (Subscription count: {tenant.sub_count})")
    else:
        logger.info("✅ All tenants have at most one subscription")

    # Check that all stores under the same tenant have the same subscription
    logger.info("Checking subscription consistency across stores...")
    inconsistent_tenants = []
    for tenant in Tenant.objects.all():
        if tenant.stores.exists():
            subscriptions = set()
            for store in tenant.stores.all():
                if store.subscription:
                    subscriptions.add(store.subscription.id)

            if len(subscriptions) > 1:
                inconsistent_tenants.append({"tenant": tenant.name, "subscriptions": subscriptions})

    if inconsistent_tenants:
        logger.warning(
            f"Found {len(inconsistent_tenants)} tenants with inconsistent store subscriptions"
        )
        for item in inconsistent_tenants:
            logger.warning(
                f"  - Tenant: {item['tenant']} has subscriptions: {item['subscriptions']}"
            )
    else:
        logger.info("✅ All stores under the same tenant have consistent subscriptions")


if __name__ == "__main__":
    # Ask for confirmation before running migration
    print("=" * 80)
    print("SUBSCRIPTION MIGRATION: STORE-BASED TO TENANT-BASED")
    print("=" * 80)
    print("\nThis script will:")
    print("1. Create a tenant for each store owner")
    print("2. Link each store to its owner's tenant")
    print("3. Move subscriptions from stores to tenants")
    print("4. Verify the migration")
    print("\n⚠️  This operation is irreversible!")
    print("Make sure you have a database backup before proceeding.")
    print("=" * 80)

    confirm = input("\nDo you want to proceed? (yes/no): ")

    if confirm.lower() in ["yes", "y"]:
        print("\nRunning migration...")
        migrate_subscriptions_to_tenants()
        print("\nRunning verification...")
        verify_migration()
        print("\n✅ Migration and verification completed!")
    else:
        print("\n❌ Migration cancelled.")
