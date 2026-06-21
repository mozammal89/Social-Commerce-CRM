"""
Constants for subscription module.
"""

# Subscription status constants
STATUS_TRIALING = "trialing"
STATUS_ACTIVE = "active"
STATUS_PAST_DUE = "past_due"
STATUS_CANCELED = "canceled"
STATUS_EXPIRED = "expired"

SUBSCRIPTION_STATUS_CHOICES = [
    (STATUS_TRIALING, "Trialing"),
    (STATUS_ACTIVE, "Active"),
    (STATUS_PAST_DUE, "Past Due"),
    (STATUS_CANCELED, "Canceled"),
    (STATUS_EXPIRED, "Expired"),
]

# Subscription event types
EVENT_CREATED = "subscription.created"
EVENT_TRIAL_STARTED = "trial.started"
EVENT_TRIAL_EXPIRED = "trial.expired"
EVENT_PAYMENT_SUCCEEDED = "payment.succeeded"
EVENT_PAYMENT_FAILED = "payment.failed"
EVENT_RENEWED = "subscription.renewed"
EVENT_UPGRADED = "subscription.upgraded"
EVENT_DOWNGRADED = "subscription.downgraded"
EVENT_CANCELED = "subscription.canceled"
EVENT_EXPIRED = "subscription.expired"
EVENT_REACTIVATED = "subscription.reactivated"
EVENT_PLAN_CHANGED = "plan.changed"

# Billing period choices
BILLING_MONTHLY = "monthly"
BILLING_YEARLY = "yearly"

BILLING_PERIOD_CHOICES = [
    (BILLING_MONTHLY, "Monthly"),
    (BILLING_YEARLY, "Yearly"),
]

# Default trial period (days)
DEFAULT_TRIAL_DAYS = 14

# Grace period for past due subscriptions (days)
DEFAULT_GRACE_PERIOD_DAYS = 7

# Currency choices
CURRENCY_BDT = "BDT"
CURRENCY_USD = "USD"
CURRENCY_EUR = "EUR"

CURRENCY_CHOICES = [
    (CURRENCY_BDT, "Bangladeshi Taka"),
    (CURRENCY_USD, "US Dollar"),
    (CURRENCY_EUR, "Euro"),
]

# Plan limit types
LIMIT_MAX_STORES = "max_stores"
LIMIT_MAX_USERS = "max_users"
LIMIT_MAX_PRODUCTS = "max_products"
LIMIT_MAX_ORDERS_PER_MONTH = "max_orders_per_month"
LIMIT_MAX_WAREHOUSES = "max_warehouses"

# Valid status transitions
VALID_STATUS_TRANSITIONS = {
    STATUS_TRIALING: [STATUS_ACTIVE, STATUS_CANCELED, STATUS_EXPIRED],
    STATUS_ACTIVE: [STATUS_PAST_DUE, STATUS_CANCELED, STATUS_EXPIRED],
    STATUS_PAST_DUE: [STATUS_ACTIVE, STATUS_CANCELED, STATUS_EXPIRED],
    STATUS_CANCELED: [STATUS_ACTIVE],
    STATUS_EXPIRED: [],
}

# Aamarpay gateway settings
AAMARPAY_STORE_ID_KEY = "AAMARPAY_STORE_ID"
AAMARPAY_SIGNATURE_KEY = "AAMARPAY_SIGNATURE_KEY"
AAMARPAY_IS_LIVE_KEY = "AAMARPAY_IS_LIVE"
AAMARPAY_BASE_URL = "https://secure.aamarpay.com"
AAMARPAY_SANDBOX_URL = "https://sandbox.aamarpay.com"

# Cache keys
CACHE_SUBSCRIPTION_PREFIX = "subscription:store:"
CACHE_PLAN_PREFIX = "plan:"
CACHE_KEY_TIMEOUT = 3600  # 1 hour
