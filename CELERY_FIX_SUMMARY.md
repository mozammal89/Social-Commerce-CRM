# Celery Task Import Fix - Summary

## Issue
Celery tasks in `apps.permissions.tasks.py` were failing with:
```
ImportError: cannot import name 'transition_status' from 'apps.permissions.services'
```

## Root Cause
The Celery tasks were trying to import `transition_status` from the wrong location:
- **Incorrect**: `from .services import transition_status` (apps.permissions.services)
- **Correct**: `from apps.subscriptions.services import transition_status` (apps.subscriptions.services)

## Fix Applied
Updated all three Celery task functions in `apps.permissions/tasks.py`:

### 1. `expire_trials()` - Line 18
```python
# Before:
from .services import transition_status

# After:
from apps.subscriptions.services import transition_status
```

### 2. `expire_active_periods()` - Line 39
```python
# Before:
from .services import transition_status

# After:
from apps.subscriptions.services import transition_status
```

### 3. `escalate_past_due()` - Line 64
```python
# Before:
from .services import transition_status

# After:
from apps.subscriptions.services import transition_status
```

## Testing Results

### ✅ Import Test
```bash
from apps.subscriptions.services import transition_status
# Result: Import successful!
```

### ✅ Task Import Test
```bash
from apps.permissions.tasks import expire_active_periods, expire_trials, escalate_past_due
# Result: All tasks imported successfully!
```

### ✅ Task Execution Test
```bash
result = expire_active_periods()
# Result: Task executed successfully! Expired 0 subscriptions.
```

## Tasks Fixed
1. **`apps.permissions.tasks.expire_trials`** - Expires trial subscriptions
2. **`apps.permissions.tasks.expire_active_periods`** - Expires active subscriptions
3. **`apps.permissions.tasks.escalate_past_due`** - Escalates past-due subscriptions

## Required Action
**Restart Celery workers** to pick up the code changes:

```bash
# Stop existing Celery workers
pkill -f "celery.*worker"

# Start Celery workers
celery -A config worker -l info
```

## Verification
After restarting, check Celery logs:
```bash
# Should see successful task execution instead of ImportError
[INFO] Expired 0 active subscriptions
[INFO] Expired 0 trials
[INFO] Escalated 0 past_due subscriptions
```

## Files Modified
- `apps/permissions/tasks.py` - Fixed import statements in 3 task functions

## Impact
- ✅ Celery scheduled tasks will now work correctly
- ✅ Subscription lifecycle automation will function as intended
- ✅ No more ImportError in Celery worker logs
- ✅ Trial expiration, subscription expiration, and past-due escalation will work

## Notes
- The `transition_status` function lives in `apps.subscriptions.services` because it's core subscription logic
- Permissions module contains subscription models, but business logic is in subscriptions module
- All three tasks are scheduled via Celery beat and run automatically