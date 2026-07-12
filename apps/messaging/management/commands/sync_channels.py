"""
sync_channels — reconcile the channel catalog registry against the DB.

Mirrors ``sync_permissions``: idempotent, safe to run on every deploy,
non-destructive by default. The catalog source of truth is
``apps.messaging.constants.DEFAULT_CHANNELS``.

Behavior:

* Channels are upserted from ``DEFAULT_CHANNELS``.
* ``is_enabled`` is only set on **create** — it is never overwritten on
  existing rows. This is deliberate: a super-admin may enable a
  ``is_enabled=False`` channel (e.g. flip Telegram on after building its
  adapter); re-syncing must not silently flip it back off. The
  admin-controlled toggle is respected.
* Channels removed from the registry are NOT auto-deleted — a connected
  account may still FK to them. Use ``--prune --confirm`` to remove.

Flags:

  --check       exit non-zero if any new channel would be added (CI use).
  --prune       remove Channel rows no longer in the registry.
  --confirm     required with --prune to actually delete.

Auto-run: wired to ``post_migrate`` via ``apps.messaging.signals`` so the
catalog reconciles on every migrate/deploy (just like sync_permissions).
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.messaging.constants import DEFAULT_CAPABILITIES, DEFAULT_CHANNELS
from apps.messaging.models import Channel


class Command(BaseCommand):
    help = "Reconcile the channel catalog registry against the Channel table."

    def add_arguments(self, parser):
        parser.add_argument(
            "--check", action="store_true",
            help="Exit non-zero if any drift is found (CI-friendly).",
        )
        parser.add_argument(
            "--prune", action="store_true",
            help="Delete Channel rows no longer in the registry.",
        )
        parser.add_argument(
            "--confirm", action="store_true",
            help="Required with --prune to actually delete rows.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        check = options.get("check", False)
        prune = options.get("prune", False)
        confirm = options.get("confirm", False)

        created = updated = 0
        registered_slugs = set()

        for spec in DEFAULT_CHANNELS:
            slug = spec["slug"]
            registered_slugs.add(slug)
            capabilities = DEFAULT_CAPABILITIES.get(slug, [])
            defaults = {
                "channel_type": spec["channel_type"],
                "name": spec["name"],
                "description": spec.get("description", ""),
                "adapter_class": spec.get("adapter_class", ""),
                "icon": spec.get("icon", ""),
                "capabilities": capabilities,
                "sort_order": spec.get("sort_order", 100),
            }
            obj, was_created = Channel.objects.update_or_create(slug=slug, defaults=defaults)
            if was_created:
                # Only seed is_enabled on first creation; never clobber an
                # admin's later toggle on re-sync.
                obj.is_enabled = spec.get("is_enabled", True)
                obj.save(update_fields=["is_enabled"])
                created += 1
            else:
                updated += 1

        # Optional prune.
        deleted = 0
        if prune and confirm:
            deleted, _ = Channel.objects.exclude(slug__in=registered_slugs).delete()
        elif prune and not confirm:
            self.stdout.write(
                self.style.WARNING("--prune requires --confirm; skipping deletion.")
            )

        msg = f"Channels: +{created} ~{updated}" + (f" -{deleted}" if deleted else "")
        total = Channel.objects.count()

        if check and created:
            self.stdout.write(self.style.WARNING(f"Drift detected: {msg}"))
            raise SystemExit(1)

        if check:
            self.stdout.write(self.style.SUCCESS(f"Catalog in sync ({total} channels)."))
        else:
            self.stdout.write(self.style.SUCCESS(f"{msg} | total={total}"))
