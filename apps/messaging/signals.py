"""
Signal handlers for the messaging app.

Currently only wires ``sync_channels`` to ``post_migrate`` so the global
channel catalog reconciles automatically on every migrate/deploy —
mirroring how ``sync_permissions`` is wired in
``apps.permissions.signals``. This keeps the catalog seeded with zero
manual steps, including new channels added to ``DEFAULT_CHANNELS``.
"""

from __future__ import annotations

import logging

from django.core.management import call_command
from django.db.models.signals import post_migrate
from django.dispatch import receiver

logger = logging.getLogger(__name__)


@receiver(post_migrate)
def run_sync_channels(sender, **kwargs):
    """Reconcile the channel catalog after migrations run.

    ``sender`` is the AppConfig that just migrated. We only run when the
    messaging app itself (or any app, since the catalog is global) has
    migrated — kept broad to catch fresh-install + incremental deploys.
    """
    try:
        call_command("sync_channels", verbosity=0)
    except Exception:  # pragma: no cover - never break migrate
        logger.exception("sync_channels failed during post_migrate")
