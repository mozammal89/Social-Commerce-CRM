"""
RBAC exception hierarchy.

All exceptions inherit from RBACError so callers can catch broadly
when needed while still being able to catch specific subclasses.
"""


class RBACError(PermissionError):
    """Base for all RBAC errors."""


class FeatureUnavailable(RBACError):
    """Raised when a feature is gated by the subscription plan."""

    def __init__(self, feature_code: str | None = None, message: str | None = None) -> None:
        self.feature_code = feature_code
        if message is None:
            message = (
                f"Feature '{feature_code}' is not available on the current plan."
                if feature_code
                else "This feature is not available on the current plan."
            )
        super().__init__(message)


class PlanLimitExceeded(RBACError):
    """Raised when a numeric plan limit is reached."""

    def __init__(self, limit_attr: str, current: int, cap: int) -> None:
        self.limit_attr = limit_attr
        self.current = current
        self.cap = cap
        super().__init__(f"{limit_attr}: {current}/{cap}")


class InvalidPermissionCode(RBACError):
    """Raised when a permission code is malformed or unknown."""

    def __init__(self, code: str | None = None) -> None:
        self.code = code
        super().__init__(
            f"Invalid permission code: {code!r}" if code else "Invalid permission code."
        )


class AuditLogImmutable(RBACError):
    """Raised when someone tries to mutate an AuditLog record."""

    def __init__(self) -> None:
        super().__init__("AuditLog is append-only and cannot be modified or deleted.")
