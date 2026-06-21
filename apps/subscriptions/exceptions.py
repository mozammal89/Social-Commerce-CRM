"""
Exception classes for subscription module.
"""


class SubscriptionError(Exception):
    """Base exception for subscription-related errors."""

    pass


class PlanLimitExceeded(SubscriptionError):
    """Raised when a user attempts to exceed their plan limits."""

    def __init__(self, limit_type, current_value, limit_value, message=None):
        self.limit_type = limit_type
        self.current_value = current_value
        self.limit_value = limit_value
        if message is None:
            message = f"Plan limit '{limit_type}' exceeded: {current_value}/{limit_value}"
        super().__init__(message)


class PaymentRequiredError(SubscriptionError):
    """Raised when payment is required for an operation."""

    def __init__(self, message="Payment is required for this operation"):
        super().__init__(message)


class SubscriptionInactiveError(SubscriptionError):
    """Raised when attempting to perform an operation on an inactive subscription."""

    def __init__(self, status, message=None):
        self.status = status
        if message is None:
            message = f"Subscription is inactive (status: {status})"
        super().__init__(message)


class PlanNotFoundError(SubscriptionError):
    """Raised when a requested plan is not found."""

    def __init__(self, plan_slug, message=None):
        self.plan_slug = plan_slug
        if message is None:
            message = f"Plan '{plan_slug}' not found"
        super().__init__(message)


class SubscriptionAlreadyExistsError(SubscriptionError):
    """Raised when attempting to create a subscription for a store that already has one."""

    def __init__(self, store_id, message=None):
        self.store_id = store_id
        if message is None:
            message = f"Store already has an active subscription"
        super().__init__(message)


class TransitionNotAllowedError(SubscriptionError):
    """Raised when attempting an invalid subscription status transition."""

    def __init__(self, current_status, new_status, message=None):
        self.current_status = current_status
        self.new_status = new_status
        if message is None:
            message = f"Cannot transition subscription from '{current_status}' to '{new_status}'"
        super().__init__(message)


class TrialExpiredError(SubscriptionError):
    """Raised when attempting to use a trial that has expired."""

    def __init__(self, trial_end_date, message=None):
        self.trial_end_date = trial_end_date
        if message is None:
            message = "Trial period has expired"
        super().__init__(message)


class PaymentGatewayError(SubscriptionError):
    """Raised when payment gateway operations fail."""

    def __init__(self, gateway_message, gateway_code=None, message=None):
        self.gateway_message = gateway_message
        self.gateway_code = gateway_code
        if message is None:
            message = f"Payment gateway error: {gateway_message}"
        super().__init__(message)
