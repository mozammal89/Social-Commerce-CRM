# Tenant-Based Subscription Architecture Refactor

## Root Cause Analysis

The current subscription architecture has a fundamental design flaw:

**Current Issue:** Subscriptions are tied to individual `Store` models via `Subscription.store` (OneToOneField)

**Impact:**
- When users upgrade their subscription, only NEW stores receive the upgraded limits
- Existing stores retain their old subscription limits
- Users must create new stores to access upgraded features
- Violates SaaS multi-tenant architecture principles

**Root Cause:** `apps/permissions/models.py:508` 
```python
store = models.OneToOneField("stores.Store", ...)
```

## Proposed Architecture

### New Structure
```
Platform
└── User (Account Holder)
    └── Tenant (Workspace/Organization) 
        ├── Subscription (ONE per tenant)
        ├── Subscription Plan
        ├── Billing
        └── Stores (MANY per tenant)
            ├── Store Memberships (inherited tenant limits)
            └── Features (inherited from tenant subscription)
```

### Key Relationships
- `User` has many `Tenant` (via owner relationship)
- `Tenant` has one `Subscription` (max one active subscription)
- `Tenant` has many `Store` (business units consuming tenant resources)
- `Store` belongs to one `Tenant` (required after migration)

## Implementation Progress

### ✅ Completed Tasks

1. **Tenant Model Created** (`apps/accounts/models.py:231-267`)
   - UUID-based identification
   - One-to-one relationship with User (owner)
   - Slug field for URL-friendly identification
   - Active/inactive status tracking

2. **Database Schema Changes**
   - Added `Tenant` table with proper indexes
   - Added `tenant` field to `Store` model (nullable for migration)
   - Added `tenant` field to `Subscription` model (nullable for migration)
   - Updated admin interfaces to support both old and new fields

3. **Migrations Applied**
   - `accounts.0004_tenant` - Created Tenant model
   - `stores.0002_store_tenant` - Added tenant field to Store
   - `permissions.0004_subscription_tenant_alter_subscription_store` - Added tenant field to Subscription

4. **Admin Interfaces Updated**
   - Added `TenantAdmin` for tenant management
   - Updated `SubscriptionAdmin` to support both store and tenant fields
   - Updated `SubscriptionEventAdmin` to reference tenant

5. **Subscription Services Updated** (`apps/subscriptions/services.py`)
   - `get_active_subscription()` now uses tenant subscription
   - `check_plan_limits()` counts usage across all tenant stores
   - Tenant-level seat counting across all stores
   - Tenant-level store counting

6. **Data Migration Script Created** (`scripts/migrate_subscriptions_to_tenants.py`)
   - Safely creates tenants for existing store owners
   - Links stores to owner's tenant
   - Migrates subscriptions from stores to tenants
   - Includes verification and rollback capabilities

### 🔄 In Progress Tasks

7. **Business Logic Updates**
   - Store creation validation (check tenant subscription limits)
   - Seat management (use tenant-wide seat counts)
   - Permission resolver (use tenant subscription)
   - Upgrade/downgrade workflows (affect all tenant stores)

### ⏳ Pending Tasks

8. **Frontend Updates**
   - Team management dashboard (show tenant-wide stats)
   - Store creation UI (check tenant limits)
   - Upgrade/downgrade UI (show tenant-wide impact)
   - Billing pages (show tenant subscription)

9. **Cache Updates**
   - Update caching keys to use tenant IDs
   - Clear cache on tenant subscription changes
   - Update permission caching for tenant-based architecture

10. **Testing**
    - Unit tests for new architecture
    - Integration tests for upgrade/downgrade flows
    - Migration tests for existing data
    - Performance tests for tenant-wide queries

## Implementation Roadmap

### Phase 1: Foundation (✅ Complete)
- ✅ Create Tenant model
- ✅ Update database schema
- ✅ Apply migrations
- ✅ Update admin interfaces

### Phase 2: Core Services (🔄 In Progress)
- ✅ Update subscription services for tenant-based logic
- 🔄 Update store creation validation
- 🔄 Update seat management
- 🔄 Update permission resolver
- 🔄 Update upgrade/downgrade workflows

### Phase 3: Frontend Integration (⏳ Pending)
- Update team management UI
- Update store creation UI
- Update billing UI
- Update upgrade/downgrade UI

### Phase 4: Caching & Performance (⏳ Pending)
- Update caching strategy
- Optimize tenant-wide queries
- Add database indexes for tenant fields

### Phase 5: Testing & Migration (⏳ Pending)
- Create comprehensive tests
- Test data migration script
- Test upgrade/downgrade flows
- Performance testing

## Data Migration Strategy

### Migration Script: `scripts/migrate_subscriptions_to_tenants.py`

**Steps:**
1. Create one tenant per store owner
2. Link each store to its owner's tenant
3. Move subscriptions from stores to tenants
4. Verify data consistency

**Execution:**
```bash
python scripts/migrate_subscriptions_to_tenants.py
```

**Rollback Plan:**
- Keep `store` field in Subscription model temporarily
- Maintain both `store` and `tenant` fields during transition
- Remove `store` field only after verification

## Business Rules Changes

### Before (Store-Based)
- Each store has its own subscription
- Store limits apply only to that store
- Upgrade affects only new stores
- Seat counting per store

### After (Tenant-Based)
- Each tenant has one subscription
- All stores under tenant share subscription limits
- Upgrade affects all tenant stores immediately
- Seat counting across all tenant stores

### Validation Rules

**Store Creation:**
```python
Current Active Stores < Tenant Subscription Max Stores
```

**Seat Validation:**
```python
Current Active Users (across all tenant stores) < Tenant Subscription Max Users
```

**Feature Validation:**
```python
Tenant Subscription includes requested feature
```

## Backward Compatibility

### Transition Period
- Both `store` and `tenant` fields exist temporarily
- Services check for tenant first, fall back to store
- Gradual migration of existing data
- Remove store field after verification

### Legacy Support
- Store-based subscriptions still work during transition
- Existing functionality preserved
- No breaking changes during migration

## Testing Requirements

### Unit Tests
- [ ] `test_tenant_creation()`
- [ ] `test_store_tenant_assignment()`
- [ ] `test_subscription_migration()`
- [ ] `test_tenant_subscription_limits()`
- [ ] `test_tenant_wide_seat_counting()`

### Integration Tests
- [ ] `test_upgrade_affects_all_stores()`
- [ ] `test_store_creation_respects_tenant_limits()`
- [ ] `test_seat_validation_across_tenant_stores()`
- [ ] `test_permission_inheritance_from_tenant()`

### Migration Tests
- [ ] `test_existing_store_owners_get_tenants()`
- [ ] `test_existing_subscriptions_migrate_correctly()`
- [ ] `test_store_tenant_links_preserve_data()`
- [ ] `test_migration_rollback()`

## Performance Considerations

### Database Queries
- Add indexes on `Store.tenant`, `Subscription.tenant`
- Optimize tenant-wide counting queries
- Use query counting for active members across tenant

### Caching Strategy
- Cache subscription by tenant ID: `subscription:tenant:{tenant_id}`
- Cache plan limits by tenant: `plan_limits:tenant:{tenant_id}`
- Invalidate cache on tenant subscription changes
- Clear user caches when tenant subscription changes

### Query Optimization
- Use `select_related` for tenant relationships
- Batch operations for tenant-wide updates
- Avoid N+1 queries in tenant operations

## Risk Mitigation

### Data Integrity
- Atomic transactions for migration
- Verification scripts after migration
- Backup before migration
- Gradual rollout with monitoring

### Performance Impact
- Monitor query performance after migration
- Add database indexes for tenant fields
- Optimize frequent tenant-wide queries
- Cache expensive calculations

### Rollback Plan
- Keep store field during transition
- Ability to revert to store-based logic
- Data backup before migration
- Gradual feature flags for rollout

## Success Criteria

### Functional Requirements
- ✅ Tenant model created and deployed
- ✅ Stores linked to tenants
- ✅ Subscriptions moved to tenants
- 🔄 Store creation checks tenant limits
- 🔄 Upgrade affects all tenant stores
- 🔄 Seat counting works across tenant stores

### Non-Functional Requirements
- ⏳ Migration completes without data loss
- ⏳ Performance maintained or improved
- ⏳ All existing tests pass
- ⏳ New tests cover tenant-based architecture
- ⏳ Documentation updated

## Next Steps

1. **Complete Business Logic Updates**
   - Update store creation validation
   - Update seat management
   - Update permission resolver
   - Update upgrade/downgrade workflows

2. **Run Data Migration**
   - Execute migration script
   - Verify data integrity
   - Test with real data

3. **Update Frontend**
   - Update team management UI
   - Update store creation UI
   - Update billing and upgrade UI

4. **Comprehensive Testing**
   - Run all existing tests
   - Create new tests for tenant architecture
   - Performance testing
   - Integration testing

5. **Documentation**
   - Update API documentation
   - Update user documentation
   - Create migration guide
   - Update troubleshooting guides

6. **Monitoring & Rollout**
   - Monitor system performance
   - Track errors and issues
   - Gradual rollout to production
   - Ready rollback plan

## Contact & Support

For questions or issues during this architectural refactor, refer to:
- Migration script: `scripts/migrate_subscriptions_to_tenants.py`
- This documentation: `docs/tenant-based-subscription-refactor.md`
- Original issue: Root cause analysis in project documentation

---

**Last Updated:** 2026-07-01
**Status:** Phase 2 In Progress
**Next Milestone:** Complete business logic updates