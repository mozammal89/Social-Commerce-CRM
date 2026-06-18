"""
AppConfig for the permissions app.

Wires signal handlers and connects the post_migrate sync hook.
"""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class PermissionsConfig(AppConfig):
    """Configuration for the permissions app."""

    name = "apps.permissions"
    label = "permissions"
    verbose_name = "Authorization & Permissions"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        """Connect signals and run-time hooks."""
        # Attach RBAC methods to User / Store.
        from . import patches
        patches.install()

        # Import signal handlers (cache invalidation + audit)
        from . import signals  # noqa: F401

        # Sync registry → DB on every migrate (idempotent).
        post_migrate.connect(
            signals.run_sync_permissions,
            sender=self,
            dispatch_uid="permissions.sync_on_migrate",
        )
