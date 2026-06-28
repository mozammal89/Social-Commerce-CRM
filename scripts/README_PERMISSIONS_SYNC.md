# Permission Sync Script

Automatically scans the codebase for permission usage patterns and helps sync the database with the codebase.

## Features

- Scans Python files for permission patterns using AST parsing
- Extracts permission codes from decorators, function calls, and assignments
- Compares with database to find missing Resources and Actions
- Generates properly formatted seeder code
- Supports preview, dry-run, and interactive modes

## Usage

```bash
# Scan the codebase and show gaps (dry run)
python scripts/sync_permissions.py scan

# Scan with detailed usage information
python scripts/sync_permissions.py scan --verbose --limit 10

# Generate seeder code for missing items
python scripts/sync_permissions.py generate

# Generate seeder code to a file
python scripts/sync_permissions.py generate -o /tmp/missing_permissions.py

# Interactive sync mode
python scripts/sync_permissions.py sync --interactive

# Force sync without confirmation
python scripts/sync_permissions.py sync --force
```

## What it finds

The script identifies:

1. **Missing Resources**: Resources referenced in code but not in database
2. **Missing Actions**: Actions for existing resources that are not defined
3. **Permission Usage**: Where each permission is used in the codebase

## Output Format

The generated seeder code includes:

- Resource definitions with suggested names and categories
- Action lists for each resource
- Example role permission assignments

## Permission Patterns Detected

- `@permission_required("orders.view")` decorators
- `permission_required = "orders.create"` class attributes
- `user_has_permission(user, store, "orders.update")` function calls
- `ROLE_PERMISSION_MATRIX` dictionary entries in seeders

## Filtering

The script automatically filters out:

- Test permissions (e.g., `anything.at_all`)
- Django app names (e.g., `apps.accounts`)
- Audit log action constants (e.g., `role.create`)
- Non-standard permission formats

## Next Steps After Sync

1. Review the generated seeder code
2. Add missing resources to your resource seeder
3. Add missing permissions to appropriate roles in `permissions_seeder.py`
4. Run your seeder scripts:
   ```bash
   python manage.py seed permissions
   python manage.py seed roles
   python manage.py seed role-permissions
   ```