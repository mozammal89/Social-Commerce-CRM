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


class DowngradeOverCapacity(RBACError):
    """Raised when a plan downgrade would leave usage above the new plan's caps.

    The frontend uses the structured ``stores`` and ``users`` lists to
    show the user exactly which rows are blocking the downgrade, so
    they can delete / soft-deactivate them and retry. The user is
    never silently dropped to a lower-resource plan; data is never
    auto-pruned.
    """

    def __init__(
        self,
        *,
        stores: list,
        users: list,
        limits: dict,
        new_plan_slug: str,
    ) -> None:
        self.stores = stores        # [{"id": uuid, "name": str}, ...]
        self.users = users          # [{"id": uuid, "email": str, ...}, ...]
        self.limits = limits        # {"max_stores": 1, "max_users": 3, ...}
        self.new_plan_slug = new_plan_slug
        super().__init__(
            f"Downgrade blocked: {len(stores)} store(s) and {len(users)} "
            f"member(s) exceed the {new_plan_slug} plan's caps."
        )
