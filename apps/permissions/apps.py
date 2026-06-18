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

        # Bug 10: register object loaders for any model with a ``store`` FK.
        # Each entry is the dotted import path of the model. Apps that
        # add new store-scoped models should call ``register_object_loader``
        # from their own AppConfig.ready() hook.
        self._register_object_loaders()

    @staticmethod
    def _register_object_loaders() -> None:
        """Register object loaders from installed apps.

        We probe a small set of well-known models defensively: the
        orders / customers / products apps may not be present yet, and
        the loader registry is a no-op for unknown kwargs.
        """
        from . import decorators

        candidates = [
            ("order_id", "apps.orders.models.Order"),
            ("customer_id", "apps.customers.models.Customer"),
            ("product_id", "apps.products.models.Product"),
            ("store_id", "apps.stores.models.Store"),
        ]
        for kwarg, path in candidates:
            try:
                module_path, _, class_name = path.rpartition(".")
                import importlib
                importlib.import_module(module_path)
            except Exception:
                # App/model not installed yet — skip silently. Once the
                # app lands, the developer can call ``register_object_loader``
                # in that app's AppConfig.ready() to enable object-level
                # checks for the corresponding kwarg.
                continue
            decorators.register_object_loader(kwarg, path)
