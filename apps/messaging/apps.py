"""
App configuration for the omnichannel messaging app.
"""

from django.apps import AppConfig


class MessagingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.messaging"
    verbose_name = "Messaging"

    def ready(self):
        # Importing the adapter registry here ensures every bundled
        # adapter self-registers its channel type on startup. Adapters
        # use the ``@register("facebook")`` decorator, so simply
        # importing the submodules is enough; no further wiring is
        # required. Importing is deferred until ``ready`` so that the
        # apps registry (and thus the model references inside adapters)
        # is fully populated first.
        from . import adapters  # noqa: F401  (side-effect import)
        # Wire ``sync_channels`` to ``post_migrate`` so the global channel
        # catalog auto-reconciles on every migrate/deploy, mirroring how
        # ``sync_permissions`` is wired in apps.permissions.
        from . import signals  # noqa: F401  (side-effect: connects signal)
